from temporalio import activity, workflow

# Activity 1: Create Docker environment and clone repo
@activity.defn(name="Setup_repo_no_compose")
async def setup_repo_environment(repo_url: str, branch: str = "main"):
    """
    Creates a Docker container, clones repo, and sets up dependencies
    """
    #import docker
    import subprocess
    import tempfile
    import os

    # client = docker.from_env()
    
    # Create a temporary directory for the build context
    temp_dir = tempfile.mkdtemp(prefix="repo_sandbox_")
    
    try:
        # Clone the repo first (to access Dockerfile/docker-compose)
        clone_result = subprocess.run(
            ["git", "clone", "-b", branch, repo_url, f"{temp_dir}/repo"],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if clone_result.returncode != 0:
            raise Exception(f"Clone failed: {clone_result.stderr}")
        
        repo_path = os.path.join(temp_dir, "repo")

        activity.heartbeat(f"Cloned repo to {repo_path}")

        return {
            "repo_path": repo_path,
            "temp_dir": temp_dir
        }
        
    except Exception as e:
        # Cleanup on failure
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise Exception(f"Setup failed: {str(e)}")
    
@activity.defn(name="remove_temp_repo")
async def remove_temp_repo(tempdir: str) -> dict:
    import shutil
    shutil.rmtree(tempdir, ignore_errors=True)
    return {
        'success': True
    }


@activity.defn(name="read_file_from_repo")
async def read_file_from_repo(environment: dict, file_path: str) -> dict:
    """
    Read a file from the cloned repo to prove it's accessible.
    
    Args:
        environment: Dict with 'repo_path', 'container_name', etc.
        file_path: Relative path to file (e.g., 'README.md', 'src/main.py')
    
    Returns:
        Dict with file contents and metadata
    """
    import os
    
    activity.heartbeat("Reading file from cloned repo")
    
    repo_path = environment['repo_path']
    full_path = os.path.join(repo_path, file_path)
    
    try:
        # Check if file exists
        if not os.path.exists(full_path):
            return {
                "success": False,
                "error": f"File not found: {file_path}",
                "repo_path": repo_path
            }
        
        # Read file contents
        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
            contents = f.read()
        
        # Get file stats
        file_size = os.path.getsize(full_path)
        line_count = len(contents.splitlines())
        
        activity.heartbeat(f"Successfully read {file_path}")
        
        return {
            "success": True,
            "file_path": file_path,
            "full_path": full_path,
            "contents": contents[:1000],  # First 1000 chars
            "file_size": file_size,
            "line_count": line_count,
            "repo_path": repo_path
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "file_path": file_path,
            "repo_path": repo_path
        }
    
@activity.defn(name="setup_python_env")
async def setup_python_env(repo_path: str):
    """
    Clone repo and create isolated Python virtual environment with dependencies
    """
    import subprocess
    import os
    import sys
    
    temp_dir = repo_path

    
    try:
        activity.heartbeat("Creating virtual environment...")
        venv_path = os.path.join(temp_dir, "venv")
        
        subprocess.run(
            [sys.executable, "-m", "venv", venv_path],
            check=True,
            capture_output=True,
            text=True
        )
        
        # Get paths to the virtual environment's Python and pip
        if os.name == 'nt':  # Windows
            python_bin = os.path.join(venv_path, "Scripts", "python.exe")
            pip_bin = os.path.join(venv_path, "Scripts", "pip.exe")
        else:  # Unix/Mac
            python_bin = os.path.join(venv_path, "bin", "python")
            pip_bin = os.path.join(venv_path, "bin", "pip")
        
        # Upgrade pip
        activity.heartbeat("Upgrading pip...")
        subprocess.run(
            [pip_bin, "install", "--upgrade", "pip"],
            check=True,
            capture_output=True,
            text=True,
            timeout=120
        )
        
        # Check for requirements files
        requirements_file = None
        possible_req_files = [
            "requirements/requirements.txt"
        ]
        
        for req_file in possible_req_files:
            req_path = os.path.join(temp_dir, req_file)
            if os.path.exists(req_path):
                requirements_file = req_path
                activity.heartbeat(f"Found {req_file}")
                break
        
        if not requirements_file:
            activity.logger.warning("No requirements file found")
        else:
            # Install dependencies based on file type
            activity.heartbeat(f"Installing dependencies from {os.path.basename(requirements_file)}...")
            
            if requirements_file.endswith(('.yaml', '.yml')):
                # For YAML requirements (like PythonRobotics)
                # First install pyyaml to read it
                subprocess.run(
                    [pip_bin, "install", "pyyaml"],
                    check=True,
                    capture_output=True,
                    timeout=120
                )
                
                # Read and parse YAML
                import yaml
                with open(requirements_file, 'r') as f:
                    reqs = yaml.safe_load(f)
                
                # Extract pip dependencies
                # PythonRobotics uses "dependencies" key with pip packages
                if isinstance(reqs, dict) and 'dependencies' in reqs:
                    packages = reqs['dependencies']
                elif isinstance(reqs, list):
                    packages = reqs
                else:
                    packages = []
                
                # Filter out conda-specific stuff and install pip packages
                pip_packages = [p for p in packages if isinstance(p, str) and not p.startswith('python')]
                
                if pip_packages:
                    result = subprocess.run(
                        [pip_bin, "install"] + pip_packages,
                        capture_output=True,
                        text=True,
                        timeout=600
                    )
                    if result.returncode != 0:
                        activity.logger.warning(f"Some packages failed to install: {result.stderr}")
            
            elif requirements_file.endswith('requirements.txt'):
                result = subprocess.run(
                    [pip_bin, "install", "-r", requirements_file],
                    capture_output=True,
                    text=True,
                    timeout=600
                )
                if result.returncode != 0:
                    raise Exception(f"Failed to install requirements: {result.stderr}")
            
            elif requirements_file.endswith('setup.py'):
                result = subprocess.run(
                    [pip_bin, "install", "-e", repo_path],
                    capture_output=True,
                    text=True,
                    timeout=600
                )
                if result.returncode != 0:
                    raise Exception(f"Failed to install package: {result.stderr}")
        
        activity.heartbeat("Environment ready")
        
        return {
            "repo_path": repo_path,
            "venv_path": venv_path,
            "python_bin": python_bin,
            "pip_bin": pip_bin,
            "temp_dir": temp_dir
        }
        
    except Exception as e:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise Exception(f"Setup failed: {str(e)}")