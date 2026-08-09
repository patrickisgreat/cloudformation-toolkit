"""Assertions for data/glue-etl."""

from __future__ import annotations


def test_database_name_avoids_hyphens(template) -> None:
    """Glue rejects hyphens in database names, and NamePrefix is hyphenated."""
    name = template.prop("Database", "DatabaseInput.Name")
    assert name["Fn::Sub"][1]["Prefix"] == {"Fn::Join": ["_", {"Fn::Split": ["-", {"Ref": "NamePrefix"}]}]}


def test_schema_changes_are_logged_not_applied(template) -> None:
    """UPDATE_IN_DATABASE rewrites the table when an inferred type changes, and
    every query relying on the old type starts failing or silently coercing."""
    policy = template.prop("Crawler", "SchemaChangePolicy")
    assert policy["UpdateBehavior"] == "LOG"
    assert policy["DeleteBehavior"] == "LOG", (
        "A lifecycle rule expiring old partitions looks to the crawler like a "
        "table that should be deprecated."
    )


def test_crawler_only_scans_new_folders(template) -> None:
    assert template.prop("Crawler", "RecrawlPolicy.RecrawlBehavior") == "CRAWL_NEW_FOLDERS_ONLY", (
        "A full recrawl lists every object in the lake and is billed per object."
    )


def test_crawler_schedule_disappears_when_empty(template) -> None:
    assert template.prop("Crawler", "Schedule")["Fn::If"][2] == {"Ref": "AWS::NoValue"}
    assert "Fn::And" in template.conditions["HasCrawlerSchedule"], (
        "A schedule with no crawler is meaningless, so the condition must "
        "require both."
    )


def test_job_bookmarks_are_enabled(template) -> None:
    arguments = template.prop("Job", "DefaultArguments")
    assert arguments["--job-bookmark-option"] == "job-bookmark-enable", (
        "Without bookmarks, an hourly job reprocesses the entire lake every "
        "hour — the most common Glue cost surprise."
    )


def test_concurrent_runs_default_to_one(template) -> None:
    assert template.default("MaxConcurrentRuns") == 1, (
        "Two concurrent runs with bookmarks enabled process overlapping data."
    )


def test_job_timeout_is_far_below_the_glue_default(template) -> None:
    assert template.default("JobTimeoutMinutes") == 60, (
        "Glue's own default is 2880 minutes — two days of billing on a hung job."
    )


def test_service_role_s3_access_is_scoped_to_the_given_buckets(template) -> None:
    statements = template.prop("ServiceRole", "Policies.0.PolicyDocument.Statement")
    read = statements[0]
    assert read["Resource"] == [
        {"Ref": "SourceBucketArn"},
        {"Fn::Sub": "${SourceBucketArn}/*"},
    ]
    assert "s3:PutObject" not in read["Action"], (
        "The source grant must be read-only; writes belong to the target bucket "
        "statement."
    )
    assert statements[1]["Fn::If"][2] == {"Ref": "AWS::NoValue"}


def test_job_and_crawler_are_independently_optional(template) -> None:
    assert template.condition_on("Crawler") == "ShouldCreateCrawler"
    assert template.condition_on("Job") == "ShouldCreateJob"
    assert template.default("EnableJob") == "false", (
        "A catalog and crawler are useful alone; a job with no script is a "
        "failing resource."
    )
