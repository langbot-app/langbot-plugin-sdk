"""Tests for the dependency manager."""
import os
import tempfile
import json
import hashlib
import pytest
from langbot_plugin.runtime.helper.depsmgr import DependencyManager


class TestDependencyManager:
    """Test cases for DependencyManager."""
    
    def test_compute_requirements_hash_nonexistent(self):
        """Test computing hash for non-existent file."""
        result = DependencyManager._compute_requirements_hash("/nonexistent/requirements.txt")
        assert result is None
    
    def test_compute_requirements_hash_existing(self):
        """Test computing hash for existing file."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("package1==1.0.0\npackage2==2.0.0\n")
            temp_file = f.name
        
        try:
            # Compute hash using the function
            result = DependencyManager._compute_requirements_hash(temp_file)
            assert result is not None
            
            # Verify it's a valid SHA256 hash (64 hex characters)
            assert len(result) == 64
            assert all(c in '0123456789abcdef' for c in result)
            
            # Verify it matches manually computed hash
            with open(temp_file, 'rb') as f:
                expected_hash = hashlib.sha256(f.read()).hexdigest()
            assert result == expected_hash
        finally:
            os.unlink(temp_file)
    
    def test_read_deps_state_nonexistent(self):
        """Test reading state from directory without state file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = DependencyManager._read_deps_state(temp_dir)
            assert result == {}
    
    def test_read_write_deps_state(self):
        """Test reading and writing dependency state."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Write state
            test_state = {
                'requirements_hash': 'abc123',
                'last_checked': '2025-01-01'
            }
            DependencyManager._write_deps_state(temp_dir, test_state)
            
            # Verify state file exists
            state_file = os.path.join(temp_dir, DependencyManager.DEPS_STATE_FILE)
            assert os.path.exists(state_file)
            
            # Read state
            result = DependencyManager._read_deps_state(temp_dir)
            assert result == test_state
    
    def test_check_and_install_dependencies_no_requirements(self):
        """Test checking dependencies when no requirements.txt exists."""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = DependencyManager.check_and_install_dependencies(temp_dir)
            assert result is False
    
    def test_check_and_install_dependencies_empty_requirements(self):
        """Test checking dependencies with empty requirements.txt."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create empty requirements.txt
            requirements_file = os.path.join(temp_dir, "requirements.txt")
            with open(requirements_file, 'w') as f:
                f.write("")
            
            result = DependencyManager.check_and_install_dependencies(temp_dir)
            assert result is False
            
            # Verify state file was created with hash of empty file
            state = DependencyManager._read_deps_state(temp_dir)
            empty_hash = DependencyManager._compute_requirements_hash(requirements_file)
            assert state.get('requirements_hash') == empty_hash
    
    def test_check_and_install_dependencies_up_to_date(self):
        """Test checking dependencies when they're already up to date."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create requirements.txt
            requirements_file = os.path.join(temp_dir, "requirements.txt")
            with open(requirements_file, 'w') as f:
                f.write("# Just a comment, no real packages\n")
            
            # Compute hash
            current_hash = DependencyManager._compute_requirements_hash(requirements_file)
            
            # Write state with current hash
            DependencyManager._write_deps_state(temp_dir, {'requirements_hash': current_hash})
            
            # Check dependencies - should return False (already up-to-date)
            result = DependencyManager.check_and_install_dependencies(temp_dir)
            assert result is False
    
    def test_mark_dependencies_installed(self):
        """Test marking dependencies as installed."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create requirements.txt
            requirements_file = os.path.join(temp_dir, "requirements.txt")
            with open(requirements_file, 'w') as f:
                f.write("package1==1.0.0\n")
            
            # Mark as installed
            DependencyManager.mark_dependencies_installed(temp_dir)
            
            # Verify state file was created with correct hash
            state = DependencyManager._read_deps_state(temp_dir)
            assert 'requirements_hash' in state
            
            # Verify hash matches
            current_hash = DependencyManager._compute_requirements_hash(requirements_file)
            assert state['requirements_hash'] == current_hash
    
    def test_mark_dependencies_installed_no_requirements(self):
        """Test marking dependencies when no requirements.txt exists."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Mark as installed (should not crash)
            DependencyManager.mark_dependencies_installed(temp_dir)
            
            # State file should not be created
            state_file = os.path.join(temp_dir, DependencyManager.DEPS_STATE_FILE)
            assert not os.path.exists(state_file)
    
    def test_requirements_change_detection(self):
        """Test that changes to requirements.txt are detected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create initial requirements.txt
            requirements_file = os.path.join(temp_dir, "requirements.txt")
            with open(requirements_file, 'w') as f:
                f.write("package1==1.0.0\n")
            
            # Mark as installed
            DependencyManager.mark_dependencies_installed(temp_dir)
            
            # Verify up-to-date
            result = DependencyManager.check_and_install_dependencies(temp_dir)
            assert result is False  # Already up-to-date
            
            # Modify requirements.txt
            with open(requirements_file, 'w') as f:
                f.write("package1==1.0.0\npackage2==2.0.0\n")
            
            # Check again - should detect the change
            # Note: We can't actually install packages in tests, so we check that
            # the hash comparison would trigger installation
            state = DependencyManager._read_deps_state(temp_dir)
            old_hash = state.get('requirements_hash')
            new_hash = DependencyManager._compute_requirements_hash(requirements_file)
            assert old_hash != new_hash
