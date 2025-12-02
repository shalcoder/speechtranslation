---
description: Upgrade the project virtual environment to Python 3.10
---

1. Stop the currently running Streamlit application (Ctrl+C in the terminal).

2. Deactivate the current virtual environment:
   ```powershell
   deactivate
   ```

3. Rename the existing virtual environment folder to back it up:
   ```powershell
   Rename-Item -Path "venv" -NewName "venv_backup"
   ```

4. Create a new virtual environment using Python 3.10:
   ```powershell
   py -3.10 -m venv venv
   ```

5. Activate the new virtual environment:
   ```powershell
   .\venv\Scripts\Activate.ps1
   ```

6. Upgrade pip and install the project dependencies:
   ```powershell
   python -m pip install --upgrade pip
   pip install -r scripts/backend/requirements.txt
   ```

7. Verify the Python version:
   ```powershell
   python --version
   ```
   (It should output Python 3.10.x)

8. Restart the application:
   ```powershell
   streamlit run scripts/backend/app.py
   ```
