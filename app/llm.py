"""Gemma 4 does the reading. Everything here only extracts; money math lives in split.py / shop.py."""

import os
import sys
from decimal import Decimal
from functools import cache

from pydantic_ai import Agent, BinaryContent, ModelRetry, PromptedOutput
from pydantic_ai.models import infer_model
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from .schemas import CounterExtract, ReceiptExtract


@cache
def get_model(env_key: str = "LLM_MODEL"):
    """Bare id (e.g. gemma-4-...) -> Gemini API. "provider:model" (e.g. deepseek:deepseek-chat) -> pydantic-ai infers it."""
    name = os.getenv(env_key) or os.environ["LLM_MODEL"]
    if ":" in name:
        return infer_model(name)
    return GoogleModel(name, provider=GoogleProvider(api_key=os.environ["GEMINI_API_KEY"]))


RECEIPT_PROMPT = """This is a photo of a restaurant or shop bill. Extract it as JSON.
- Copy every number exactly as printed. Prices are in the bill's currency (usually Zambian Kwacha, K / ZMW).
- One entry per printed line item: name, qty (1 if not shown), unit_price if printed, line_total (qty x unit price as printed).
- subtotal = the printed subtotal; if none is printed, the sum of the line totals.
- tax = VAT / sales tax amount; service = service charge amount; 0 if absent.
- If the bill says the VAT is already included in the prices ("VAT incl", "incl. VAT"), set tax_included true.
- total = the final amount due as printed.
- Never invent items. Anything you cannot read clearly goes into `unreadable` as a short note instead of a guess.
- Ignore payment lines (cash tendered, change, card)."""

COUNTER_PROMPT = """This photo shows products on a shop counter, or a handwritten order list.
List each distinct product you can see with how many units there are.
- label: the product as you'd name it, including brand and size if visible (e.g. "Coke 500ml bottle").
- qty: count the units carefully; for a handwritten list copy the quantity written.
- confidence: 0 to 1, how sure you are of label and qty.
Do not include prices. Do not invent products that are not visible."""

receipt_reader = Agent(output_type=PromptedOutput(ReceiptExtract), retries=2, name="receipt_reader")
counter_reader = Agent(output_type=PromptedOutput(CounterExtract), retries=2, name="counter_reader")


def close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= max(Decimal(1), abs(b) / 100)


@receipt_reader.output_validator
def check_totals(out: ReceiptExtract) -> ReceiptExtract:
    lines = sum((i.line_total for i in out.items), Decimal(0))
    if not close(lines, out.subtotal):
        raise ModelRetry(f"The line totals sum to {lines} but subtotal is {out.subtotal}; re-read the line items.")
    expected = out.subtotal + out.service + (0 if out.tax_included else out.tax)
    if not close(expected, out.total):
        raise ModelRetry(f"subtotal + tax + service = {expected} but total is {out.total}; re-read the totals "
                         "(set tax_included if VAT is already inside the prices).")
    return out


async def read_receipt(data: bytes, media_type: str) -> ReceiptExtract:
    r = await receipt_reader.run([RECEIPT_PROMPT, BinaryContent(data, media_type=media_type)], model=get_model())
    return r.output


async def read_counter(data: bytes, media_type: str) -> CounterExtract:
    r = await counter_reader.run([COUNTER_PROMPT, BinaryContent(data, media_type=media_type)], model=get_model())
    return r.output


if __name__ == "__main__":  # uv run python -m app.llm receipt photo.jpg
    import asyncio
    import mimetypes

    from dotenv import load_dotenv

    load_dotenv()
    kind, path = sys.argv[1], sys.argv[2]
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    fn = {"receipt": read_receipt, "counter": read_counter}[kind]
    print(asyncio.run(fn(open(path, "rb").read(), mime)).model_dump_json(indent=2))
