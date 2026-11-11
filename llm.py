import http.client
import json
import os

TYPES = {"decision", "responsibility", "risk", "dependency", "blocker", "open_question", "next_action", "contact", "unfinished"}
PROMPT = (
    "Read the project text below. Return only a JSON list. Each item needs: type (one of "
    + ", ".join(sorted(TYPES))
    + "), statement (one short sentence) and quote (an exact copy of the words in the text that support it).\n\n"
)


def parse_items(reply):
    try:
        items = json.loads(reply[reply.index("[") : reply.rindex("]") + 1])
    except ValueError:
        return None
    return [item for item in items if isinstance(item, dict) and item.get("type") in TYPES and item.get("statement")]


def llm_extract(text):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    body = json.dumps(
        {
            "model": os.environ.get("LLM_MODEL", "claude-sonnet-5-5"),
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": PROMPT + text[:12000]}],
        }
    )
    headers = {"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"}
    connection = http.client.HTTPSConnection("api.anthropic.com", timeout=30)
    try:
        connection.request("POST", "/v1/messages", body, headers)
        reply = json.loads(connection.getresponse().read())["content"][0]["text"]
    except (OSError, ValueError, KeyError, IndexError):
        return None
    finally:
        connection.close()
    return parse_items(reply)
