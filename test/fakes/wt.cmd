@echo off
rem BYO wt stub (Windows): one-line JSON, exit 0. No vendor login. No -p/-c required.
echo {"ok": true, "harness": "wt", "argv": "%*"}
exit /b 0
