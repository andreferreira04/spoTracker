# SpoTracker

## How to Configure SpoTracker to Run at Startup

Follow these steps to set up SpoTracker so that it runs automatically when your computer starts:

### Prerequisites
- Ensure Python (version 3 or above) is installed on your system.

---

### Steps for Configuration on Windows:

1. **Locate the Startup Folder:**
   - Press `Win + R` to open the "Run" dialog box.
   - Type `shell:startup` and press Enter. This will open the Startup folder.

2. **Create a Shortcut for the Script:**
   - Right-click inside the Startup folder and select **New > Shortcut**.
   - In the "Item location" field, enter the following command:
     ```plaintext
     "C:\path\to\pythonw.exe" "C:\path\to\music-register.py"
     ```
     Replace `C:\path\to` with the actual paths to your Python interpreter (`pythonw.exe`) and the script (`music-register.py`).

3. **Complete the Shortcut Setup:**
   - Click **Next**.
   - Give the shortcut a name (e.g., `SpoTracker`).
   - Click **Finish**.

---

### First-Time Execution
- The first time you restart your PC, you might be prompted with a dialog asking for confirmation to execute the script.  
  Select **"Don't ask again"** and click **Yes** to allow the script to run automatically.

---

### Verifying the Script is Running
- Open **Task Manager** (`Ctrl + Shift + Esc`).
- Look for a running process named **Python**. This confirms that the script is active.

---

### Additional Notes
- Using `pythonw.exe` ensures the script runs without a visible console window.
- If you need to stop the script temporarily, end the Python process via Task Manager.

With these steps completed, SpoTracker will run seamlessly whenever your computer starts.