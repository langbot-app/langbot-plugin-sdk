"""Dependency manager for tracking and ensuring plugin dependencies are installed."""
import os
import hashlib
import json
from typing import Optional
from langbot_plugin.runtime.helper import pkgmgr as pkgmgr_helper


class DependencyManager:
    """Manager for tracking and installing plugin dependencies."""
    
    DEPS_STATE_FILE = ".deps_state.json"
    
    @staticmethod
    def _compute_requirements_hash(requirements_file: str) -> Optional[str]:
        """Compute SHA256 hash of requirements.txt file using streaming approach.
        
        Args:
            requirements_file: Path to requirements.txt file
            
        Returns:
            Hex digest of SHA256 hash, or None if file doesn't exist
        """
        if not os.path.exists(requirements_file):
            return None
        
        try:
            hash_obj = hashlib.sha256()
            with open(requirements_file, 'rb') as f:
                # Read and hash in chunks for memory efficiency
                for chunk in iter(lambda: f.read(4096), b''):
                    hash_obj.update(chunk)
            return hash_obj.hexdigest()
        except Exception as e:
            print(f"Warning: Failed to compute hash for {requirements_file}: {e}")
            return None
    
    @staticmethod
    def _read_deps_state(plugin_path: str) -> dict:
        """Read dependency state from plugin directory.
        
        Args:
            plugin_path: Path to plugin directory
            
        Returns:
            Dictionary containing dependency state information
        """
        state_file = os.path.join(plugin_path, DependencyManager.DEPS_STATE_FILE)
        if not os.path.exists(state_file):
            return {}
        
        try:
            with open(state_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Failed to read deps state from {state_file}: {e}")
            return {}
    
    @staticmethod
    def _write_deps_state(plugin_path: str, state: dict) -> None:
        """Write dependency state to plugin directory.
        
        Args:
            plugin_path: Path to plugin directory
            state: Dictionary containing dependency state information
        """
        state_file = os.path.join(plugin_path, DependencyManager.DEPS_STATE_FILE)
        try:
            with open(state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            print(f"Warning: Failed to write deps state to {state_file}: {e}")
    
    @staticmethod
    def check_and_install_dependencies(plugin_path: str) -> bool:
        """Check if dependencies need to be installed and install them if necessary.
        
        This function checks if the plugin's requirements.txt has been installed
        in the current environment by comparing the hash of requirements.txt
        with the stored hash in the dependency state file.
        
        Args:
            plugin_path: Path to plugin directory
            
        Returns:
            True if dependencies were installed (or reinstalled), False if already up-to-date
        """
        requirements_file = os.path.join(plugin_path, "requirements.txt")
        
        # If no requirements.txt exists, no dependencies to install
        if not os.path.exists(requirements_file):
            return False
        
        # Compute current requirements hash
        current_hash = DependencyManager._compute_requirements_hash(requirements_file)
        if current_hash is None:
            return False
        
        # Read stored state
        state = DependencyManager._read_deps_state(plugin_path)
        stored_hash = state.get('requirements_hash')
        
        # Check if dependencies need to be installed
        if stored_hash == current_hash:
            # Dependencies are up-to-date
            return False
        
        # For empty or whitespace-only requirements file, just mark as installed without calling pip
        # Check file size first for efficiency
        try:
            file_size = os.path.getsize(requirements_file)
            if file_size == 0:
                # Empty file, just update state
                state['requirements_hash'] = current_hash
                DependencyManager._write_deps_state(plugin_path, state)
                return False
            elif file_size < 100:  # Small file, check if it's only whitespace
                with open(requirements_file, 'r') as f:
                    content = f.read().strip()
                    if not content:
                        # Whitespace-only file, just update state
                        state['requirements_hash'] = current_hash
                        DependencyManager._write_deps_state(plugin_path, state)
                        return False
        except Exception as e:
            print(f"Warning: Failed to check {requirements_file}: {e}")
            return False
        
        # Install dependencies
        print(f"Installing dependencies for plugin at {plugin_path}")
        try:
            pkgmgr_helper.install_requirements(requirements_file)
            
            # Update state file with new hash
            state['requirements_hash'] = current_hash
            DependencyManager._write_deps_state(plugin_path, state)
            
            print(f"Successfully installed dependencies for {plugin_path}")
            return True
        except Exception as e:
            print(f"Error installing dependencies for {plugin_path}: {e}")
            # Don't update state file on failure
            return False
    
    @staticmethod
    def mark_dependencies_installed(plugin_path: str) -> None:
        """Mark dependencies as installed for a plugin.
        
        This is typically called after successful plugin installation.
        
        Args:
            plugin_path: Path to plugin directory
        """
        requirements_file = os.path.join(plugin_path, "requirements.txt")
        current_hash = DependencyManager._compute_requirements_hash(requirements_file)
        
        if current_hash is not None:
            state = DependencyManager._read_deps_state(plugin_path)
            state['requirements_hash'] = current_hash
            DependencyManager._write_deps_state(plugin_path, state)
