"""
Homework 1: Home Price Prediction using Prompt Engineering
------------------------------------------------------------
This script does NOT train a machine learning model. Instead, it builds
a "few-shot prompt" for a large language model (LLM) such as Gemini.

The idea: instead of training a model on the dataset, we show the LLM a
handful of real examples (house attributes -> known price) directly inside
the prompt text. The LLM then uses that pattern to guess the price of a
new house we describe at the end of the prompt.

Steps this script performs:
1. Read california_housing_train.csv
2. Randomly pick between 60 and 70 rows to use as "few-shot" examples
3. Turn each example row into a plain-English sentence
4. Combine all the examples into one big prompt
5. Ask the user for a new house's attributes and add them to the prompt
6. Send the prompt to Gemini and print the predicted price

The Gemini API key is reused from the my_test_chat_app project's
.env.local file (GOOGLE_GENAI_API_KEY) instead of being duplicated here.
The key is only ever loaded into memory and used in a request header -
it is never printed.
"""

import csv
import json
import random
import urllib.error
import urllib.request

CSV_FILE = "california_housing_train.csv"

# The homework's own .env.local, read directly (not copied) so the key
# lives in exactly one place. This script only reads that file.
ENV_FILE = "/Users/mallikarjunchunduru/Desktop/my_test_chat_app/.env.local"
ENV_KEY_NAME = "GOOGLE_GENAI_API_KEY"

# Try Gemini 3.5 Flash first, since that's what the homework specifies.
# If it's unavailable or over quota, fall back to the next model in this
# list (both are already known to work from the main chat app).
MODEL_CANDIDATES = ["gemini-3.5-flash", "gemini-3-flash-preview", "gemini-3.6-flash"]

GEMINI_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


def load_dataset(file_path):
    """Reads the CSV file and returns a list of dictionaries, one per row."""
    with open(file_path, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return rows


def pick_random_examples(rows, min_count=60, max_count=70):
    """Randomly picks between min_count and max_count rows from the dataset."""
    num_examples = random.randint(min_count, max_count)
    return random.sample(rows, num_examples)


def format_example(row):
    """
    Converts one CSV row into a plain-English example sentence that shows
    the house's attributes and its known median house value.
    """
    return (
        f"- A house at longitude {row['longitude']}, latitude {row['latitude']}, "
        f"housing median age {row['housing_median_age']} years, "
        f"{row['total_rooms']} total rooms, {row['total_bedrooms']} total bedrooms, "
        f"a population of {row['population']}, {row['households']} households, "
        f"and a median income of {row['median_income']} "
        f"has a median house value of ${row['median_house_value']}."
    )


def format_new_house(new_house):
    """Converts the new house (the one we want a prediction for) into the
    same plain-English style as the examples, but without a price."""
    return (
        f"- A house at longitude {new_house['longitude']}, latitude {new_house['latitude']}, "
        f"housing median age {new_house['housing_median_age']} years, "
        f"{new_house['total_rooms']} total rooms, {new_house['total_bedrooms']} total bedrooms, "
        f"a population of {new_house['population']}, {new_house['households']} households, "
        f"and a median income of {new_house['median_income']}."
    )


def get_new_house_from_user():
    """
    Asks the user to type in the attributes of a new house, one at a time.
    Returns a dictionary in the same shape as a dataset row, so it can be
    used with format_new_house() and build_prompt().
    """
    print("\nEnter the attributes of the new house you want a price for:")

    return {
        "longitude": float(input("  Longitude: ")),
        "latitude": float(input("  Latitude: ")),
        "housing_median_age": float(input("  Housing median age (years): ")),
        "total_rooms": float(input("  Total rooms: ")),
        "total_bedrooms": float(input("  Total bedrooms: ")),
        "population": float(input("  Population: ")),
        "households": float(input("  Households: ")),
        "median_income": float(input("  Median income (in tens of thousands, e.g. 4.5 = $45,000): ")),
    }


def load_api_key(env_path):
    """
    Reads GOOGLE_GENAI_API_KEY out of a .env-style file and returns it.
    The key is only returned to the caller - this function never prints it.
    """
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith(f"{ENV_KEY_NAME}="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError(f"{ENV_KEY_NAME} not found in {env_path}")


def describe_error(http_status, message):
    """Turns a raw HTTP status + error message into a short, friendly reason."""
    if http_status == 429:
        return "rate limit / quota exceeded"
    if http_status == 503:
        return "model temporarily overloaded"
    if http_status == 404:
        return "model not found / not available"
    if http_status == 400:
        return f"request rejected ({message})"
    return f"HTTP {http_status} error ({message})"


def call_gemini(model, api_key, prompt):
    """
    Sends the prompt to one Gemini model via the REST API and returns the
    predicted text. Raises RuntimeError with a friendly message on failure -
    it never includes the API key in that message.
    """
    url = GEMINI_URL_TEMPLATE.format(model=model)
    body = json.dumps(
        {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    ).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as err:
        error_body = json.loads(err.read().decode("utf-8"))
        message = error_body.get("error", {}).get("message", str(err))
        raise RuntimeError(describe_error(err.code, message)) from err

    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError("no candidates returned in the response")

    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts or "text" not in parts[0]:
        raise RuntimeError("model returned an empty response")

    return parts[0]["text"]


def predict_price(prompt, api_key):
    """
    Tries each model in MODEL_CANDIDATES in order. Reports any failure
    (quota, overload, etc.) before moving to the next model. Returns
    (model_used, predicted_text) for the first model that succeeds.
    """
    for model in MODEL_CANDIDATES:
        print(f"\nTrying model: {model} ...")
        try:
            text = call_gemini(model, api_key, prompt)
            print(f"  Success with {model}.")
            return model, text
        except RuntimeError as err:
            print(f"  {model} failed: {err}")

    raise RuntimeError(
        "All Gemini models were unavailable. Please try again later."
    )


def build_prompt(example_rows, new_house):
    """
    Builds the full few-shot prompt:
      instructions + example houses with known prices + the new house
      we want the model to predict a price for.
    """
    intro = (
        "You are a real estate pricing expert.\n"
        "Below are examples of houses in California with their attributes "
        "and their known median house value.\n"
        "Study the pattern in these examples, then predict the median house "
        "value for the new house described at the end.\n\n"
        "Examples:\n"
    )

    examples_text = "\n".join(format_example(row) for row in example_rows)

    question = (
        "\n\nNow predict the median house value for this new house:\n"
        f"{format_new_house(new_house)}\n\n"
        "What is the predicted median house value? "
        "Respond with a single dollar amount."
    )

    return intro + examples_text + question


if __name__ == "__main__":
    # Step 1: Load all rows from the dataset
    all_rows = load_dataset(CSV_FILE)
    print(f"Loaded {len(all_rows)} rows from {CSV_FILE}")

    # Step 2: Randomly select 60-70 rows to use as few-shot examples
    example_rows = pick_random_examples(all_rows)
    print(f"Selected {len(example_rows)} random rows as few-shot examples")

    # Step 3: Ask the user to describe the NEW house they want a price for.
    new_house = get_new_house_from_user()

    # Step 4: Build the final prompt
    prompt = build_prompt(example_rows, new_house)

    # Step 5: Show the generated prompt
    print("\n" + "=" * 70)
    print("GENERATED PROMPT:")
    print("=" * 70)
    print(prompt)

    # Step 6: Load the API key (never printed) and call Gemini.
    # Any failure (quota exceeded, all models overloaded, etc.) is caught
    # here so the program ends with a clear message instead of a crash.
    try:
        api_key = load_api_key(ENV_FILE)
        model_used, predicted_text = predict_price(prompt, api_key)
    except RuntimeError as err:
        print("\n" + "=" * 70)
        print(f"COULD NOT GET A PREDICTION: {err}")
        print("=" * 70)
    else:
        # Step 7: Show the result clearly
        print("\n" + "=" * 70)
        print(f"PREDICTED MEDIAN HOUSE VALUE (model: {model_used}):")
        print("=" * 70)
        print(predicted_text.strip())
