@echo off
cd /d "C:\Users\NEHITH\Documents\JOBHUNT\PWP_jobhunt"
"C:\Users\NEHITH\Documents\JOBHUNT\PWP_jobhunt\.venv\Scripts\python.exe" -m jobhunt run --send >> "out\scheduler.log" 2>&1
