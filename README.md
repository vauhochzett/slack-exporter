# Export conversations from Slack

Forked from [margaritageleta /
slack-export-history](https://github.com/margaritageleta/slack-export-history)

## Get API token

To use this app, you need an API token. Get it as follows:

Go to https://api.slack.com/apps and `Create New App`. Choose your Workspace and press `Create App`. Then, click on your app and go to `Add features and functionality` → `Permissions` → `Scopes` and add the following scopes in `User Token Scopes` (be careful, `User Token Scopes` NOT `Bot Token Scopes`):

- `channels:history`
- `channels:read`
- `groups:history`
- `groups:read`
- `im:history`
- `im:read`
- `mpim:history`
- `mpim:read`
- `users:read`

Then install the app in your workspace (you can go to `OAuth & Permissions` section and press `Reinstall app`), accept the permissions and copy the OAuth Access Token.

## Run app

Execute `python export.py <your-access-token>`
