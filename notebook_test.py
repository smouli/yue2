# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///

import marimo

__generated_with = "0.24.0"
app = marimo.App()


@app.cell
def _():
    from pathlib import Path
    import os
    import marimo as mo

    secrets_file = Path.home() / ".yue2/.secrets.env"

    result = f"""
    **Secrets file path:** {secrets_file}
    **Exists:** {secrets_file.exists()}
    **WANDB_API_KEY in env:** {"WANDB_API_KEY" in os.environ}
    """

    if secrets_file.exists():
        result += f"\n**File contents (first line):** {secrets_file.read_text().splitlines()[0][:50]}..."
        for line in secrets_file.read_text().splitlines():
            k, _, v = line.partition("=")
            os.environ[k] = v
        result += f"\n**After loading - WANDB_API_KEY in env:** {'WANDB_API_KEY' in os.environ}"

    mo.md(result)
    return

if __name__ == "__main__":
    app.run()
