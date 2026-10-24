"""Local entry point. Run `python app.py` or `flask --app app run`."""

import os

from innovative import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False)
