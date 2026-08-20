"""Assertions for foundation/cognito-user-pool."""

from __future__ import annotations

NOVALUE = {"Ref": "AWS::NoValue"}


# 1. Secure defaults -----------------------------------------------------------

def test_self_signup_is_off_by_default(template) -> None:
    assert template.default("AllowSelfSignUp") == "false", (
        "A pool that quietly accepts signups is an open directory anyone can "
        "join. Consumer products opt in; everyone else gets admin-created users."
    )
    assert template.prop("UserPool", "AdminCreateUserConfig.AllowAdminCreateUserOnly")[
        "Fn::If"
    ] == ["AllowsSelfSignUp", False, True], (
        "The toggle must actually reach AllowAdminCreateUserOnly - inverted, "
        "since the Cognito property is the negation of the parameter."
    )


def test_password_policy_is_strong_by_default(template) -> None:
    assert template.default("PasswordMinimumLength") == 12
    policy = template.prop("UserPool", "Policies.PasswordPolicy")
    for requirement in ("RequireLowercase", "RequireUppercase", "RequireNumbers", "RequireSymbols"):
        assert policy[requirement] is True, (
            f"{requirement} is not a parameter on purpose: character-class "
            "requirements are table stakes, and a knob to weaken them is a "
            "knob someone will turn."
        )


def test_the_user_directory_survives_everything(template) -> None:
    assert template.deletion_policy("UserPool") == "Retain", (
        "A user pool holds real people's accounts; a rollback must never be "
        "able to delete them."
    )
    assert template.resource("UserPool").get("UpdateReplacePolicy") == "Retain", (
        "Several UserPool properties (Schema, UsernameAttributes) replace the "
        "resource on change - without Retain, an innocent-looking edit deletes "
        "every user."
    )
    assert template.prop("UserPool", "DeletionProtection") == "ACTIVE", (
        "Retain covers CloudFormation; DeletionProtection covers the console "
        "and the CLI."
    )


def test_the_client_is_public_and_never_sees_a_plaintext_password(template) -> None:
    assert template.prop("WebClient", "GenerateSecret") is False, (
        "A secret shipped in a JS bundle or mobile binary is published, not "
        "protected. SPA/mobile clients are public clients by design."
    )
    flows = template.prop("WebClient", "ExplicitAuthFlows")
    assert "ALLOW_USER_PASSWORD_AUTH" not in flows and "ALLOW_ADMIN_USER_PASSWORD_AUTH" not in flows, (
        "SRP proves the password without transmitting it; the PASSWORD_AUTH "
        "flows send it in the request body."
    )
    assert "ALLOW_USER_SRP_AUTH" in flows


def test_signin_errors_do_not_leak_which_emails_exist(template) -> None:
    assert template.prop("WebClient", "PreventUserExistenceErrors") == "ENABLED", (
        "Distinct 'no such user' / 'wrong password' errors let anyone enumerate "
        "the membership of the pool from the login form."
    )
    assert template.prop("WebClient", "EnableTokenRevocation") is True


def test_email_changes_require_verifying_the_new_address(template) -> None:
    assert template.prop(
        "UserPool", "UserAttributeUpdateSettings.AttributesRequireVerificationBeforeUpdate"
    ) == ["email"], (
        "Without this, a hijacked session can rebind the account to the "
        "attacker's address and own the recovery path."
    )


def test_mfa_is_offered_by_default_and_is_totp_only(template) -> None:
    assert template.default("MfaConfiguration") == "OPTIONAL"
    enabled = template.prop("UserPool", "EnabledMfas")
    assert enabled["Fn::If"] == ["MfaIsAvailable", ["SOFTWARE_TOKEN_MFA"], NOVALUE], (
        "SMS MFA needs an SNS role, costs per message, and is the weaker "
        "factor - TOTP is the only one offered."
    )


# 2. Conditional wiring --------------------------------------------------------

def test_oauth_settings_appear_only_with_callback_urls(template) -> None:
    """Cognito rejects AllowedOAuthFlowsUserPoolClient with no CallbackURLs, so
    the whole OAuth block must stand and fall together."""
    for prop in ("AllowedOAuthFlowsUserPoolClient", "AllowedOAuthFlows", "AllowedOAuthScopes", "CallbackURLs"):
        value = template.prop("WebClient", prop)
        assert value["Fn::If"][0] == "HasOauthClient", f"{prop} is not gated on HasOauthClient"
        assert value["Fn::If"][2] == NOVALUE
    assert template.prop("WebClient", "AllowedOAuthFlows")["Fn::If"][1] == ["code"], (
        "Implicit flow puts tokens in the URL, where they land in browser "
        "history and server logs. Code flow only."
    )


def test_hosted_ui_domain_is_conditional(template) -> None:
    assert template.default("HostedUiDomainPrefix") == ""
    assert template.condition_on("HostedUiDomain") == "HasHostedUiDomain"
    assert template.output("HostedUiUrl").get("Condition") == "HasHostedUiDomain", (
        "An output referencing a conditional resource must carry the same "
        "Condition, or the no-domain stack fails to create."
    )


# 3. Pass-through --------------------------------------------------------------

def test_token_lifetimes_reach_the_client_in_the_declared_units(template) -> None:
    assert template.prop("WebClient", "AccessTokenValidity") == {"Ref": "AccessTokenValidityMinutes"}
    assert template.prop("WebClient", "RefreshTokenValidity") == {"Ref": "RefreshTokenValidityDays"}
    units = template.prop("WebClient", "TokenValidityUnits")
    assert units == {"AccessToken": "minutes", "IdToken": "minutes", "RefreshToken": "days"}, (
        "The parameter names promise minutes/days; without TokenValidityUnits "
        "Cognito interprets the numbers as hours/days and a '60 minute' token "
        "quietly lives 60 hours."
    )


# 4. Interface -----------------------------------------------------------------

def test_outputs_include_the_jwt_issuer_and_audience_pair(template) -> None:
    """serverless/http-api's JWT authorizer needs both halves: ProviderUrl is
    its JwtIssuer, WebClientId its JwtAudience. Renaming either breaks the
    composition."""
    assert template.output("ProviderUrl")["Value"] == {"Fn::GetAtt": ["UserPool", "ProviderURL"]}
    assert template.output("WebClientId")["Value"] == {"Ref": "WebClient"}


def test_name_prefix_is_the_only_required_parameter(template) -> None:
    assert template.required_parameters == ["NamePrefix"], (
        "Everything else has a defensible default, so the pool deploys with "
        "one parameter."
    )
