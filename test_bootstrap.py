import sys
import time
import os

# Add the backend directory to sys.path so the 'app' module can be found
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backend'))

def trace_calls(frame, event, arg):
    if event == 'call':
        func_name = frame.f_code.co_name
        if "app/startup" in frame.f_code.co_filename or "app/simulation" in frame.f_code.co_filename:
            print(f"CALL: {func_name} at {frame.f_code.co_filename}:{frame.f_code.co_firstlineno}")
    return trace_calls

sys.settrace(trace_calls)

from app.startup.bootstrap import run_bootstrap
print("Starting run_bootstrap...")
run_bootstrap()
print("Finished!")
