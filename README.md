# Lab Effects SEO Monitor

An in-house SEO tool for labeffects.com. It does three jobs on a schedule:

1. **Crawl** the live site every night and flag technical and content problems
   (broken links, redirect chains, bad title tags, missing meta descriptions,
   missing alt text, FAQ schema that does not match the page, house-style slips
   like em dashes and British spelling, leftover `[placeholder]` text).
2. **Pull Google Search Console** data every day: which queries each page ranks
   for, where positions moved, which pages are close to page one.
3. **Report** what changed to Slack, so the team sees only new problems and
   new opportunities, not the whole list every time.

Keyword volume and competitor data come from a plug-in provider. Out of the box
it runs with no paid data (`KEYWORD_PROVIDER=none`). Set
`KEYWORD_PROVIDER=dataforseo` plus an API login to rent that data per query.

## Layout

```
seo/
  config.py        settings, all from environment variables
  db.py            one small database (SQLite locally, Postgres on Render)
  cli.py           python -m seo <command>
  crawl/           sitemap discovery, polite fetching, the checks
  gsc/             Google Search Console pull
  keywords/        provider interface: none | dataforseo
  report/          diff against the last run, Slack post
tests/             fixtures and unit tests for the checks
render.yaml        the scheduled jobs on Render
```

## Commands

```
python -m seo crawl            # crawl the site, store findings
python -m seo gsc              # pull the last 3 days from Search Console
python -m seo report           # build and post the report
python -m seo all              # crawl, gsc, report
python -m seo crawl --dry-run  # crawl and print findings, store nothing
```

## Setup

1. Copy `.env.example` to `.env` and fill it in.
2. `pip install -r requirements.txt`
3. `python -m seo crawl --dry-run` to see it work with no credentials.
4. For Search Console: create a Google Cloud service account, enable the
   Search Console API, add the service account's email as a user on the
   labeffects.com property in Search Console, and paste the JSON key into
   `GSC_SERVICE_ACCOUNT_JSON`.
5. For Slack: create an incoming webhook for the channel and set
   `SLACK_WEBHOOK_URL`.

## Deploying

`render.yaml` defines two cron jobs (nightly crawl + report, daily Search
Console pull) and a Postgres database. Connect the repo in Render, set the
environment variables, done.

## Rules for changes

Same as the theme repo: branch from `main`, open a pull request, Dustin
reviews and merges. Never commit `.env` or any key.
