from pathlib import Path
import json
import hashlib
import zlib
import time


from pygit.core.objects import (
    GitObject,
    Blob,
    Tree,
    Commit
)


class Repository:
    def __init__(self,path="."):
        self.path = Path(path).resolve()
        self.git_dir = self.path / ".pygit"
        
        # .git/objects
        self.objects_dir = self.git_dir / "objects"
        
        # .git/refs
        self.ref_dir = self.git_dir / "refs"
        self.heads_dir = self.ref_dir / "heads"
        # HEAD file
        self.head_file = self.git_dir / "HEAD"
        
        # .git/index
        self.index_file = self.git_dir / "index"
    
    def init(self) -> bool:
        if self.git_dir.exists():
            return False
        
        # create directories 
        self.git_dir.mkdir()
        self.objects_dir.mkdir()
        self.ref_dir.mkdir()
        self.heads_dir.mkdir()
        
        # create initial HEAD pointing to a branch 
        self.head_file.write_text("ref: refs/heads/master\n")
        self.save_index({})
        self.index_file.write_text(json.dumps({}, indent=2))
        
        print(f"Initialized empty Git repository in {self.git_dir}")
        
        return True
    
    def store_object(self,obj:GitObject) -> str:
        obj_hash = obj.hash()
        obj_dir = self.objects_dir / obj_hash[:2]
        obj_file = obj_dir / obj_hash[2:]
        
        if not obj_file.exists():
            obj_dir.mkdir(exist_ok=True)
            obj_file.write_bytes(obj.serialize())
        
        return obj_hash
    
    def load_index(self) -> Dict[str,str]:
        if not self.index_file.exists():
            return {} # incase user delete, ie edge case
        
        
        try:
            return json.loads(self.index_file.read_text())
        except:
            return {}

    def save_index(self, index: Dict[str,str]):
        self.index_file.write_text(json.dumps(index, indent=2))
        
    def add_file(self,path:str):
        full_path = self.path / path
        if not full_path.exists():
            raise FileNotFoundError(f"Path {path} not found")    
        #Read the file content
        content = full_path.read_bytes()
        #Create BLOB object from the content
        blob = Blob(content)
        #store the blob onject in db(.git/objects)
        blob_hash = self.store_object(blob)
        # update index to include the file
        index = self.load_index()
        index[path] = blob_hash
        self.save_index(index)
        
        print(f"Added {path}")
    
    def add_directory(self, path:str):
        full_path = self.path / path
        if not full_path.exists():
            raise FileNotFoundError(f"Directory {path} not found") 
        
        if not full_path.is_dir():
            raise ValueError(f"{path} is not a directory")
        
        index = self.load_index() 
        
        added_count  = 0
        # recursively traverse the directory
        for file_path in full_path.rglob("*"):
            if file_path.is_file():
                if ".pygit" in file_path.parts:
                    continue
                rel_path = str(file_path.relative_to(self.path))
                # create & store blob object
                content = file_path.read_bytes()
                blob = Blob(content)
                blob_hash = self.store_object(blob)
                # update index
                rel_path = str(file_path.relative_to(self.path))
                index[rel_path] = blob_hash
                added_count+=1
        self.save_index(index)
        
        if added_count > 0:
            print(f"Added {added_count} files from directory{path}")
        else :
            print(f"Directory {path} already up to date")
        # create blob objects for all files
        # store all blobs in the object database (.git/objects)
        # updates the index to include all the files
        
        
        pass
    
    def add_path(self,path:str) -> None:
        full_path = self.path / path
        if not full_path.exists():
            raise FileNotFoundError(f"Path {path} not found")
        
        if full_path.is_file():
            self.add_file(path)
        elif full_path.is_dir():
            self.add_directory(path) 
        else: 
            raise ValueError(f"{path} is neither a file nor a directory")
    
    def load_object(self, obj_hash: str)-> GitObject:
        obj_dir = self.objects_dir / obj_hash[:2]
        obj_file = obj_dir / obj_hash[2:]
        
        if not obj_file.exists():
            raise FileNotFoundError(f"Object {obj_hash} not found")
        
        return GitObject.deserialize(obj_file.read_bytes())
    
    def create_tree_from_index(self):
        index = self.load_index()
        if not index:
            tree=Tree()
            return self.store_object(tree)
        
        #  dirs = {
        #   "test":{
        #       "test2":{
        #          "hi.txt": "hash"
        #     }
        #  }}
            
        dirs = {}
        files = {}
        
        for file_path , blob_hash in index.items():
            parts = file_path.split("/")
            
            if len(parts)==1:
                # file in root
                files[parts[0]]= blob_hash
            else:
                dir_name = parts[0]
                if dir_name not in dirs:
                    dirs[dir_name] = {}
                
                current = dirs[dir_name]
                # taking all directories except last, where files are
                for part in parts[1:-1]:
                    if part not in current:
                        current[part] = {}
                    
                    current = current[part]
                current[parts[-1]] = blob_hash
            
        def create_tree_recursive(entries_dict:Dict):
            tree=Tree()
            for name,blob_hash in entries_dict.items():
                if isinstance(blob_hash,str):
                    tree.add_entry("100644",name,blob_hash)
                if isinstance(blob_hash,dict):
                    subtree_hash = create_tree_recursive(blob_hash)
                    tree.add_entry("40000",name,subtree_hash)
            return self.store_object(tree)
        root_entries  ={**files}
        
        for dir_name, dir_contents in dirs.items():
            root_entries[dir_name] = dir_contents
        
        return create_tree_recursive(root_entries)
       # tree is required to know what file belongs to which folder and what blob is ass with the file
       
    def get_current_branch(self) -> str:
        if not self.head_file.exists():
            return "master"
        head_content = self.head_file.read_text().strip()
        if head_content.startswith("ref: refs/heads/"):
            return head_content[16:]
        return "HEAD" # detached HEAD
    
    def get_branch_commit(self, current_branch: str):
        branch_file = self.heads_dir / current_branch
        
        if branch_file.exists():
            return branch_file.read_text().strip()
        
        return None

    def set_branch_commit(self, current_branch: str, commit_hash:str):
        branch_file = self.heads_dir / current_branch
        branch_file.write_text(commit_hash + "\n")
        
    def commit(
        self,
        message: str,
        author: str="PyGit User <user@pygit.com>",
        ):
        
            # create a tree object form the index (staging area)
            tree_hash = self.create_tree_from_index()
            
            current_branch = self.get_current_branch()
            parent_commit = self.get_branch_commit(current_branch)
            parent_hashes  = [parent_commit] if parent_commit else []
            
            index = self.load_index()
            if not index:
                print("nothing to commit, working tree clean")
                return None
            
            if parent_commit:
                parent_git_commit_obj = self.load_object(parent_commit)
                parent_commit_data = Commit.from_content(parent_git_commit_obj.content)
                if tree_hash == parent_commit_data.tree_hash:
                    print("nothing to commit, working tree clean")
                    return None
            commit = Commit(
                tree_hash=tree_hash,
                parent_hashes=parent_hashes,
                author=author,
                committer=author,
                message=message,
            )
            commit_hash = self.store_object(commit)
            
            self.set_branch_commit(current_branch,commit_hash)
            self.save_index({})
            print(f"Created commit {commit_hash} on branch {current_branch}")
            return commit_hash
    
    
    def get_files_from_tree_recursive(self, tree_hash:str, prefix: str="",):
        files= set()
        try:
            tree_obj = self.load_object(tree_hash)
            tree = Tree.from_content(tree_obj.content)
            #list <tuple<str,str,str>>
            
            for mode, name, obj_hash in tree.entries:
                full_name = f"{prefix}{name}"
                if mode.startswith("100"):
                    files.add(full_name)
                elif mode.startswith("400"):
                    subtree_files = self.get_files_from_tree_recursive(
                        obj_hash, f"{full_name}/"
                    )
                    files.update(subtree_files)
        except Exception as e:
            print(f"Warning: Could not read tree { tree_hash}: {e}")
        return files

                
    def checkout(self, branch:str, create_branch: bool):
        previous_branch = self.get_current_branch()
        files_to_clear = set()
        previous_commit_hash=None
        try:
            previous_commit_hash = self.get_branch_commit(previous_branch)
            if previous_commit_hash:
                prev_commit_object = self.load_object(previous_commit_hash)
                prev_commit = Commit.from_content(prev_commit_object.content)
                if prev_commit.tree_hash:
                    files_to_clear = self.get_files_from_tree_recursive(
                        prev_commit.tree_hash
                    )
        except Exception:
            files_to_clear = set()
            
        # created/moved to a new branch
        branch_file = self.heads_dir / branch
        if not branch_file.exists():
            if create_branch:
                    if previous_commit_hash:    
                        self.set_branch_commit(branch, previous_commit_hash)
                        print(f"Created new branch {branch}")
                    else:
                        print("No commits yet, cannot create a branch")
                        return 
            else:
                print(f"Branch '{branch}' not found.")
                print(
                    "Use 'python3 main.py checkout -b {branch} to create and switch to a new branch"
                )
                return
        self.head_file.write_text(f"ref: refs/heads/{branch}\n")
        
        # restore working directory 
        self.restore_working_directory(branch,files_to_clear)
        print(f"Switched to branch {branch}")
    
    def restore_tree(self, tree_hash:str, path:Path):
        tree_obj = self.load_object(tree_hash)
        tree = Tree.from_content(tree_obj.content)
        #list <tuple<str,str,str>>
        
        for mode, name, obj_hash in tree.entries:
            file_path = path / name
            if mode.startswith("100"):
                blob_obj = self.load_object(obj_hash)
                # blob = Blob(blob_obj.content)
                # no need to wrap it again 
                file_path.parent.mkdir(parents=True, exist_ok=True)
                # to make sure parent directories exist
                file_path.write_bytes(blob_obj.content)
            elif mode.startswith("400"):
                file_path.mkdir(exist_ok=True)
                self.restore_tree(
                    obj_hash, file_path
                )
        
    def restore_working_directory(
        self,
        branch:str,
        files_to_clear: set[str],
    ):
        target_commit_hash = self.get_branch_commit(branch)
        if not target_commit_hash:
            return 
        
        # remove files tracked by previous branch
        for rel_path in sorted(files_to_clear):
            file_path = self.path / rel_path
            try:
                if file_path.is_file():
                    file_path.unlink()
            except Exception:
                pass
        target_commit_obj = self.load_object(target_commit_hash)
        target_commit = Commit.from_content(target_commit_obj.content)
        
        if target_commit.tree_hash:
            self.restore_tree(target_commit.tree_hash,self.path)
        
        self.save_index({})
    
    def get_commit_files(self) -> Dict[str, str]:

        current_branch = self.get_current_branch()

        commit_hash = self.get_branch_commit(current_branch)

        if not commit_hash:
            return {}

        commit_obj = self.load_object(commit_hash)

        commit = Commit.from_content(commit_obj.content)

        files = {}

        def walk_tree(tree_hash, prefix=""):

            tree_obj = self.load_object(tree_hash)

            tree = Tree.from_content(tree_obj.content)

            for mode, name, obj_hash in tree.entries:

                full_name = f"{prefix}{name}"

                if mode.startswith("100"):
                    files[full_name] = obj_hash

                elif mode.startswith("400"):
                    walk_tree(obj_hash, full_name + "/")

        walk_tree(commit.tree_hash)

        return files
            
    def status(self):

        index = self.load_index()

        committed = self.get_commit_files()

        staged = []
        modified = []
        untracked = []
        
        # staged files 
        for path, blob_hash in index.items():

            if path not in committed:
                staged.append(path)

            elif committed[path] != blob_hash:
                staged.append(path)

        # working directory 

        IGNORE_DIRS = {
            ".git",
            ".pygit",
            "venv",
            "__pycache__",
            ".pytest_cache"
        }
        for file_path in self.path.rglob("*"):

            if not file_path.is_file():
                continue

            if any(part in IGNORE_DIRS for part  in file_path.parts):
                continue

            rel_path = str(file_path.relative_to(self.path))

            content = file_path.read_bytes()

            working_hash = Blob(content).hash()

            # tracked in index
            if rel_path in index:

                # modified after staging
                if index[rel_path] != working_hash:
                    modified.append(rel_path)

            # tracked only in commit
            elif rel_path in committed:

                # modified but unstaged
                if committed[rel_path] != working_hash:
                    modified.append(rel_path)

            # completely unknown file
            else:
                untracked.append(rel_path)

        # output 
        print("\n=== STATUS ===\n")

        if staged:
            print("Changes to be committed:")

            for f in staged:
                print(f"    staged: {f}")

            print()

        if modified:
            print("Changes not staged:")

            for f in modified:
                print(f"    modified: {f}")

        print()

        if untracked:
            print("Untracked files:")

            for f in untracked:
                print(f"    {f}")

            print()

        if not staged and not modified and not untracked:
            print("Working tree clean")

    def log(self,oneline=False,graph=False):

        current_branch = self.get_current_branch()
        commit_hash = self.get_branch_commit(current_branch)
        branches = self.get_all_branches()
        if not commit_hash:
            print("No commits yet")
            return 

        while commit_hash:
            commit_obj = self.load_object(commit_hash)
            commit = Commit.from_content(commit_obj.content)


            labels = []

            for name, hash_ in branches.items():

                if hash_ == commit_hash:
                    labels.append(name)

            label_text = ""

            if labels:
                label_text = f" ({', '.join(labels)})"

            prefix = ""

            if graph:
                prefix = "* "

            if oneline:
                print(
                    f"[green]{prefix}[/green]"
                    f"[yellow]{commit_hash[:7]}[/yellow] "
                    f"[white]{commit.message}[/white]"
                    f"[red]{label_text}[/red]"
                )
            else:

                print(f"\ncommit {commit_hash}")

                if labels:
                    print(f"Branches: {', '.join(labels)}")

                print(f"Author: {commit.author}")

                readable_time = time.strftime(
                    "%Y-%m-%d %H:%M:%S",
                    time.localtime(commit.timestamp)
                )

                print(f"Date: {readable_time}")

                print(f"\n    {commit.message}\n")
            if commit.parent_hashes:
                commit_hash = commit.parent_hashes[0]
            else:
                break
    
    def get_all_branches(self):
        branches = {}

        for branch in self.heads_dir.iterdir():
            if branch.is_file():
                branches[branch.name]=branch.read_text().strip()
        
        return branches
