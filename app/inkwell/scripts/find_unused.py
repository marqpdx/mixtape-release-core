import subprocess


# Paths to scan
SCAN_PATHS = ["ai/"]

# Files or directories to exclude from scan
EXCLUDE_PATHS = [
    "ai/migrations/",
    "ai/__pycache__/",
    "ai/experimental/",  # example
]

# Create the vulture command
exclude_args = [f"--exclude={','.join(EXCLUDE_PATHS)}"]
cmd = ["vulture", *SCAN_PATHS, *exclude_args]

# Run and print output
logger.info("Running: {' '.join(cmd)}\n")
subprocess.run(cmd, check=False)
