from flask import Flask, render_template
from threading import Thread

app = Flask('__name__')

@app.route('/')
def home():
  return "Hello. I am alive!"


def run():
  app.run(host='0.0.0.0', port=8080)  # Run the app on port 8080


def keep_alive():
  t = Thread(target=run)
  t.start()
