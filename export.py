import argparse
import datetime as dt
import importlib
import json
import os
import random
import re
import shutil
import sys
from typing import Dict, List

import requests
from pick import pick


def auth(token):
    """ Check to make sure the auth token is valid. """
    r = requests.post("https://slack.com/api/auth.test", data={"token": token})
    if not r.ok:
        print(f"Auth unsuccessful. Status code: {r.status_code}")
        return False

    data = r.json()
    if data["ok"]:
        print(
            f"Auth successful.\n"
            f"  Team: {data['team']} (ID {data['team_id']})\n"
            f"  User: {data['user']} (ID {data['user_id']})"
        )
        return True
    else:
        print(f"Auth error: {data['error']}")
        return False


def retrieve_data(endpoint, payload):
    r = requests.get(f"https://slack.com/api/{endpoint}", params=payload)
    if not r.ok:
        raise IOError(f"Data retrieval failed. Status code: {r.status_code}")

    data = r.json()
    if not data["ok"]:
        raise IOError(f"Error: {data['error']}")

    return data


def get_users(users_data) -> Dict[str, Dict[str, str]]:
    users: Dict[str, Dict[str, str]] = dict()
    for member in users_data["members"]:
        users[member["id"]] = {
            # Real users have a display_name, bots don't.
            "name": member["profile"]["display_name"] or member["name"],
            "real_name": member["profile"]["real_name"],
        }
    return users


def get_conversations(conversations_data, users: Dict[str, Dict[str, str]]):
    conversations: Dict[str, Dict[str, str]] = dict()
    for conversation in conversations_data["channels"]:
        conv_id = conversation["id"]
        conversations[conv_id] = dict()
        if conversation["is_im"]:
            conv_partner: str = users[conversation["user"]]["name"]
            conversations[conv_id].update(
                {
                    "title": f"@{conv_partner}",
                    "desc": (f"IM with " f"{conv_partner}"),
                    "who": (
                        f"{users[conversation['user']]['name']} "
                        f"(ID {conversation['user']})"
                    ),
                }
            )
        elif conversation["is_mpim"]:
            purpose: str = conversation["purpose"]["value"]
            if purpose.startswith("Group messaging with: "):
                purpose = purpose[22:]

            conversations[conv_id].update(
                {
                    "title": purpose,
                    "desc": f"Group IM: " f"{purpose}",
                    "who": (
                        f"{users[conversation['creator']]['name']} "
                        f"(ID {conversation['creator']})"
                    ),
                }
            )
        elif conversation["is_channel"] or conversation["is_group"]:
            conversations[conv_id].update(
                {
                    "title": f"#{conversation['name']}",
                    "desc": (
                        f"Channel \"{conversation['name']}\" "
                        f"({'private' if conversation['is_private'] else 'public'}) "
                    ),
                    "who": (
                        f"{users[conversation['creator']]['name']} "
                        f"(ID {conversation['creator']})"
                    ),
                }
            )
        else:
            raise IOError(f"Unknown conversation type.\nConversation:\n{conversation}")

    return conversations


def _collect_messages(messages_data, users) -> List[Dict[str, str]]:
    if not messages_data["ok"]:
        raise IOError(f"Received error response: {messages_data['error']}")

    messages: List[Dict[str, str]] = []
    for msg in messages_data["messages"]:
        author: Dict[str, str]
        try:
            author = users[msg["user"]]
        except KeyError:
            print(f"Unknown user: {msg['user']}")
            print(f"Message: {msg['text']}")
            author = {"real_name": f"Unknown – ID {msg['user']}", "name": "Unknown"}
        messages.append(
            {
                "user": f"{author['real_name']} (@{author['name']})",
                "text": msg["text"],
                "ts": msg["ts"],
                "ts_readable": dt.datetime.fromtimestamp(float(msg["ts"])).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
            }
        )
    return messages


def fetch_and_get_messages(payload, users) -> List[Dict[str, str]]:
    messages_data = None
    messages: List[Dict[str, str]] = []

    # Repeat loop while there are older messages
    while True:
        # `messages_data` is None for the first request
        if messages_data is not None:
            # change the 'latest' argument to fetch older messages
            payload["latest"] = messages_data["messages"][-1]["ts"]

        messages_data = retrieve_data("conversations.history", payload)
        messages.extend(_collect_messages(messages_data, users))

        if not messages_data["has_more"]:
            break

    return messages


def replace_mentions(messages: List[Dict[str, str]], users: Dict[str, Dict[str, str]]):
    for message in messages:
        text: str = message["text"]
        m = re.findall(r"(<@((\w|\d)+)>)", text)
        for repl, usr_id, _ in m:
            try:
                message["text"] = text.replace(repl, f"@{users[usr_id]['name']}")
            except KeyError:
                pass


def main():
    parser = argparse.ArgumentParser(description="Export Slack history")
    parser.add_argument("token", help="Slack Access Token")
    parser.add_argument(
        "--extra-users",
        action="store_true",
        help="Use a list of additional users not registered in the Slack.",
    )
    args = parser.parse_args()

    # Make sure the authentication token is valid
    if not auth(args.token):
        sys.exit(1)

    # Define the payload to do requests at Slack API
    PAYLOAD = {
        "token": args.token,
    }

    # Retrieve users and conversations lists
    print("Fetching users...")
    users_data = retrieve_data("users.list", PAYLOAD)
    users: Dict[str, Dict[str, str]] = get_users(users_data)
    if args.extra_users:
        extra = importlib.import_module("users")
        users.update(extra.EXTRA_USERS)

    message_types: List[str] = ["public_channel", "private_channel", "mpim", "im"]
    selection = pick(
        message_types,
        "Select the conversation type (at least one; [space] to select, [enter] to confirm):",
        multiselect=True,
        min_selection_count=1,
    )

    PAYLOAD["types"] = ", ".join([o for o, i in selection])
    print("Fetching conversations...")
    conversations_data = retrieve_data("conversations.list", PAYLOAD)
    conversations: Dict[str, Dict[str, str]] = get_conversations(
        conversations_data, users
    )

    # Selection
    _, index = pick(
        [
            f"{conv_data['title'] if len(conv_data['title']) <= 20 else conv_data['title'][:17] + '...':<20}"
            + f" | {conv_data['desc']}"
            for conv_id, conv_data in conversations.items()
        ],
        "Select the conversation to export:",
    )
    chosen_conversation = list(conversations.keys())[index]
    PAYLOAD["channel"] = chosen_conversation

    # Download messages
    print("Downloading...")
    messages: List[Dict[str, str]] = fetch_and_get_messages(PAYLOAD, users)
    # Replace mention tags with @name
    replace_mentions(messages, users)

    # Export messages
    print("Exporting...")
    # Create a directory in which to store the data
    export_dir: str = "export"
    export_file: str = (
        f"{conversations[chosen_conversation]['title']}_"
        + dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        + ".json"
    )
    export_path: str = os.path.join(export_dir, export_file)
    if os.path.lexists(export_path):
        print(f"Export file '{export_path}' exists.")
        sys.exit(1)

    os.makedirs(export_dir, exist_ok=True)

    with open(export_path, "w") as f:
        json.dump(messages, f, indent="\t")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
