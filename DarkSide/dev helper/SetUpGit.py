import subprocess

def execute_command(command, scope):
    try:
        # Run the command and capture output
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        print(f"Successfully executed {scope} command: {command}\nOutput: {result.stdout}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to execute {scope} command: {command}\nError: {e.stderr}")
        return False


def setup_git_config(configs):
    for config in configs:
        global_cmd = f'git config --global {config}'
        local_cmd = f'git config {config}'
        
        # Try to execute global command, if it fails, fallback to local
        if not execute_command(global_cmd, 'global'):
            execute_command(local_cmd, 'local')

if __name__ == "__main__":
    # List of git configuration parameters
    git_configs = [
        'user.name "Sen Zhang"',
        'user.email zsenarchitect@gmail.com'
    ]
    
    setup_git_config(git_configs)
