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
        
        repo_path = f"{temp_dir}/repo"

        activity.heartbeat(f"Cloned repo to {repo_path}")

        return {
            "repo_path": repo_path,
            "temp_dir": temp_dir
        }
        
        """
        # Check if Dockerfile exists
        dockerfile_path = f"{repo_path}/Dockerfile"
        
        # Build Docker image from the repo's Dockerfile
        activity.heartbeat("Building Docker image from Dockerfile...")
        
        image, build_logs = client.images.build(
            path=repo_path,
            dockerfile="docker-compose.yml",  # Use the repo's Dockerfile
            tag=f"repo-sandbox:{repo_url.split('/')[-1].replace('.git', '')}"
        )
        
        # Log build output
        for log in build_logs:
            if 'stream' in log:
                print(log['stream'].strip())
        
        # Create and start container
        activity.heartbeat("Starting container...")
        
        container = client.containers.run(
            image.id,
            command="sleep infinity",  # Keep container running
            detach=True,
            working_dir="/workspace",
            volumes={
                repo_path: {"bind": "/workspace", "mode": "rw"}
            },
            remove=False
        )
        
        return {
            "container_id": container.id,
            "image_id": image.id,
            "repo_path": repo_path,
            "temp_dir": temp_dir
        }
        """
        
    except Exception as e:
        # Cleanup on failure
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise Exception(f"Setup failed: {str(e)}")


# Activity 2: Alternative - Use docker-compose if that's what the repo uses
@activity.defn(name="Setup_repo_compose")
async def setup_repo_with_compose(repo_url: str, branch: str = "main"):
    """
    Uses docker-compose.yml from the repo
    """
    import subprocess
    import tempfile

    temp_dir = tempfile.mkdtemp(prefix="repo_sandbox_")
    
    try:
        # Clone repo
        subprocess.run(
            ["git", "clone", "-b", branch, repo_url, f"{temp_dir}/repo"],
            check=True,
            capture_output=True
        )
        
        repo_path = f"{temp_dir}/repo"
        
        # Start services with docker-compose
        activity.heartbeat("Starting docker-compose services...")
        
        result = subprocess.run(
            ["docker compose", "up", "-d"],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise Exception(f"docker-compose failed: {result.stderr}")
        
        # Get container ID of main service
        # You'll need to know which service is your main one
        get_container = subprocess.run(
            ["docker compose", "ps", "-q"],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        
        container_id = get_container.stdout.strip().split('\n')[0]
        
        return {
            "container_id": container_id,
            "repo_path": repo_path,
            "temp_dir": temp_dir,
            "compose_project": repo_path
        }
        
    except Exception as e:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


# Activity 3: Run commands in the container
@activity.defn(name="run_command_in_sandbox")
async def run_command_in_sandbox(container_id: str, command: str):
    """
    Execute a command inside the Docker container
    """
    import docker

    client = docker.from_env()
    container = client.containers.get(container_id)
    
    result = container.exec_run(command, workdir="/workspace")
    
    return {
        "exit_code": result.exit_code,
        "output": result.output.decode('utf-8')
    }


# Activity 4: Cleanup
@activity.defn(name="cleanup_sandbox")
async def cleanup_sandbox(environment: dict):
    """
    Stop container, remove images, delete temp files
    """
    import docker

    client = docker.from_env()
    
    try:
        # Stop and remove container
        if "container_id" in environment:
            container = client.containers.get(environment["container_id"])
            container.stop(timeout=10)
            container.remove()
        
        # Remove image if needed
        if "image_id" in environment:
            client.images.remove(environment["image_id"], force=True)
        
        # Remove temp directory
        if "temp_dir" in environment:
            import shutil
            shutil.rmtree(environment["temp_dir"], ignore_errors=True)
            
    except Exception as e:
        print(f"Cleanup warning: {e}")

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