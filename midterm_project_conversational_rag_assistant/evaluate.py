"""Measure the assistant's accuracy, retrieval relevance and memory on the demo files (needs Ollama running).

    python evaluate.py            # prints a per-question table and the scores
"""
import sys

from assistant import Assistant

# These strings represent answers that should be treated as "not found" rather
# than guessed. This keeps evaluation strict for unsupported questions.
NOT_FOUND = ["not find", "couldn't find", "could not", "no information", "not mention", "not specified", "does not contain", "not provided"]

# Single-turn tests: Excel, handbook, and unsupported questions.
# Each item is a (user_question, accepted_answer_patterns) pair.
SINGLE = [
    # Excel: total revenue
    ("What is the total revenue?", ["221840"]),
    ("What is the total revenue across all regions?", ["221840"]),
    ("What was the revenue in the East region?", ["10700"]),
    ("What was the revenue in the North region?", ["91840"]),
    ("What was the revenue in the South region?", ["40210"]),
    ("What was the revenue in the West region?", ["79090"]),

    # Excel: transaction counts
    ("How many sales transactions are recorded in total?", ["40"]),
    ("How many sales transactions were recorded in the East region?", ["3"]),
    ("How many sales transactions were recorded in the North region?", ["12"]),
    ("How many sales transactions were recorded in the South region?", ["11"]),
    ("How many sales transactions were recorded in the West region?", ["14"]),

    # Excel: units sold
    ("How many units were sold in the East region?", ["33"]),
    ("How many units were sold in the North region?", ["155"]),
    ("How many units were sold in the South region?", ["91"]),
    ("How many units were sold in the West region?", ["129"]),

    # Excel: comparisons and targets
    ("Which region had the highest revenue?", ["north"]),
    ("Which region had the lowest revenue?", ["east"]),
    ("What is the Q3 revenue target for the West region?", ["22000"]),
    ("What is the Q3 revenue target for the East region?", ["28000"]),
    ("Which salesperson sold the most revenue?", ["tarek"]),

    # Excel: schema and source understanding
    ("What are the column names in the Sales sheet?", ["Date", "Region", "Salesperson", "Product", "Units", "Unit Price", "Revenue"]),
    ("How many sales records are in the Sales sheet?", ["40"]),
    ("What is the difference between Units and Revenue?", ["units", "revenue"]),

    # Employee handbook
    ("How many days of annual leave do employees get?", ["21"]),
    ("How many sick leave days are granted per year?", ["10"]),
    ("How many annual leave days can employees carry over?", ["5"]),
    ("What is the daily meal allowance for business travel?", ["25"]),
    ("How often must passwords be changed?", ["90"]),
    ("How big is the yearly learning budget?", ["1200"]),

    # Unsupported information: the assistant should not invent an answer
    ("Who is the CEO of Nile Tech?", NOT_FOUND),
]


# Multi-turn tests: follow-up questions must use conversation history.
# These cases verify that the assistant keeps memory across several turns and can
# resolve pronouns and earlier context correctly.
CHATS = [
    [
        ("How many days of annual leave do employees get?", ["21"]),
        ("How many of them can I carry over to next year?", ["5"]),
        ("And what about sick leave?", ["10"]),
    ],
    [
        ("Which region had the highest revenue?", ["north"]),
        ("And the lowest?", ["east"]),
        ("What is its Q3 revenue target?", ["28000"]),
    ],
    [
        ("What is the total revenue?", ["221840"]),
        ("How many transactions contributed to that total?", ["40"]),
        ("Which region had the highest revenue?", ["north"]),
    ],
    [
        ("How often must passwords be changed?", ["90"]),
        ("What is the daily meal allowance?", ["25"]),
        ("What was the first question I asked you?", ["password"]),
    ],
    
    # Remember a user preference across unrelated questions
    [
        ("My favorite color is blue. Remember that for this conversation.", ["blue"]),
        ("How many days of annual leave do employees get?", ["21"]),
        ("What is my favorite color?", ["blue"]),
    ],

    # Remember an exact code across several questions
    [
        ("Remember this code: BLUE-724.", ["BLUE-724"]),
        ("What is the daily meal allowance?", ["25"]),
        ("What is the total revenue across all regions?", ["221840"]),
        ("What code did I ask you to remember?", ["BLUE-724"]),
    ],

    # Distinguish the first message from the first question
    [
        ("My favorite color is blue. Remember that for this conversation.", ["blue"]),
        ("How many days of annual leave do employees get?", ["21"]),
        ("What was the first message I sent you?", ["my favorite color is blue"]),
    ],
    [
        ("My favorite color is blue. Remember that for this conversation.", ["blue"]),
        ("How many days of annual leave do employees get?", ["21"]),
        ("What was the first question I asked you?", ["annual leave"]),
    ],

]



# Comparison helpers.
# These functions normalize strings so tests tolerate capitalization and number
# formatting differences while remaining strict about the expected fact.
def matches(answer, options):
    norm = lambda s: s.lower().replace(",", "")
    return any(norm(o) in norm(answer) for o in options)


def run_single(bot, cases):
    ok, hit = [], []
    for q, expected in cases:
        bot.reset()
        reply, docs = bot.ask(q)
        ok.append(matches(reply, expected))
        hit.append(expected is NOT_FOUND or matches("\n".join(d.page_content for d in docs), expected))
        print(f"  {'PASS' if ok[-1] else 'FAIL'}  retrieval {'hit ' if hit[-1] else 'MISS'}  {q}\n        -> {reply.strip()[:110]!r}")
    return ok, hit


# Multi-turn validation.
# Each chat is evaluated in sequence so that conversation memory is tested as a
# real interaction instead of a set of isolated question/answer pairs.
def run_chats(bot, chats):
    results = []
    for chat in chats:
        bot.reset()
        for q, expected in chat:
            reply, _ = bot.ask(q)
            results.append(matches(reply, expected))
            print(f"  {'PASS' if results[-1] else 'FAIL'}  {q}\n        -> {reply.strip()[:110]!r}")
        print()
    return results


# Entry point for the benchmark run.
# It instantiates the assistant, scores the single-turn and multi-turn cases, and
# exits with a fail status if any required fact is missing or if the memory is wrong.
if __name__ == "__main__":
    bot = Assistant(["data/handbook.pdf", "data/sales.xlsx"])
    print("Single questions:")
    ok, hit = run_single(bot, SINGLE)
    print("\nConversations (follow-ups need memory):")
    chat_ok = run_chats(bot, CHATS)
    print(f"Answer accuracy:        {sum(ok)}/{len(ok)}\nRetrieval relevance:    {sum(hit)}/{len(hit)}  (the right passage was retrieved)\n"
          f"Follow-up / memory:     {sum(chat_ok)}/{len(chat_ok)}")
    sys.exit(0 if all(ok) and all(chat_ok) else 1)