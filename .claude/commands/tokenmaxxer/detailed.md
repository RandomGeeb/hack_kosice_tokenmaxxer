Launch the tokenmaxxer web dashboard (app.py) and open it in the browser.

Steps:
1. Check if the server is already running: `lsof -ti:5001`
2. If not running, start it in the background using the venv: `.venv/bin/python -c "from app import app; app.run(debug=False, port=5001)"` with run_in_background=true
3. Wait 1 second for the server to start
4. Open the dashboard in the default browser: `open http://localhost:5001`
5. Tell the user: "Dashboard running at http://localhost:5001"

If the server was already running, skip to step 4.
Note: port 5000 is reserved by macOS AirPlay Receiver, so we use 5001.
If starting the server fails, show the error output to the user.
