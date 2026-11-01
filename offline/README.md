# Running Sanctio offline (Windows)

Runs Sanctio (API and dashboard) and the SwiftShip demo on your own laptop, with no internet.
Without internet, the built-in rule-based engine answers; every security check works exactly the same.

**Once, while you have internet:** install Python 3.11+ (tick "Add python.exe to PATH") and Node.js LTS,
then double-click `setup_offline.bat`.

**Each time you demo:** double-click `start_offline.bat`. Two windows open (Sanctio and SwiftShip) and
the browser opens:

| What | Address | Sign in |
|---|---|---|
| SwiftShip (customer side) | http://localhost:8100 | pick a customer |
| Sanctio dashboard | http://localhost:8000 | `demo@swiftship.test` / `Passw0rd!23` |

Running `start_offline.bat` again resets the demo data. To stop, close the two windows.
To use the AI when you do have internet, edit `settings.bat` as it explains.
