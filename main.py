from __future__ import annotations
import argparse
import sys
from pathlib import Path
import json
import hashlib
import zlib
import time
from typing import Dict,List,Tuple,Optional

class GitObject:
    def __init__(self,obj_type:str,content:bytes):
        self.type = obj_type
        self.content = content
    def hash(self)->str:
         # f(<type> <size>\0<content>)
         header = f"{self.type} {len(self.content)}\0".encode()
         return hashlib.sha1(header + self.content).hexdigest()
        
        #compressing the data to lossless compression
    def serialize(self) ->bytes:   
        header = f"{self.type} {len(self.content)}\0".encode()
        return zlib.compress(header+self.content)
    
    @classmethod
    def deserialize(cls,data:bytes)->GitObject:
        decompressed = zlib.decompress(data)
        null_idx = decompressed.find(b"\0")
        header = decompressed[:null_idx].decode()
        content = decompressed[null_idx + 1 :]
        
        obj_type, _ = header.split(" ")
        return cls(obj_type, content)
    
    # binary large object 
class Blob(GitObject):
    def __init__(self, content:bytes):
        super().__init__('blob', content)
    
class Tree(GitObject):
    def __init__(self, entries: List[Tuple[str,str,str]]=None):
        self.entries = entries or []
        content = self._serialize_entries()
        super().__init__("tree", content)
    
    def _serialize_entries(self) ->bytes:
        # <mode> <name> \0 <hash> 
        content = b""
        for mode, name, obj_hash in sorted(self.entries):
            content += f"{mode} {name}\0".encode()
            content += bytes.fromhex(obj_hash)
        
        return content
    
    def add_entry(self,mode:str,name:str,obj_hash:str):
        self.entries.append((mode,name,obj_hash))
        self.content = self._serialize_entries()
           
    @classmethod
    def from_content(cls,content:bytes)->Tree:
        tree = cls()
        i=0
        
        while i < len(content):
            null_idx = content.find(b"\0",i)
            # 100644 README.md\0[20 bytes of content hash]100644 README.md\0[20 bytes of content hash]   
            if null_idx ==-1:
                break
            
            mode_name = content[i:null_idx].decode()
            mode, name = mode_name.split(" ", 1)
            # the "1" splits the content in the first split it founds
            #"hi hi hi" -> "hi", "hi hi"
            obj_hash = content[null_idx+1:null_idx+21].hex()
            tree.entries.append((mode,name,obj_hash))
            i = null_idx +21
            
        return tree
            

class Commit(GitObject):
    def __init__(
        self,
        tree_hash: str,
        parent_hashes:List[str],
        author:str,
        committer:str,
        message:str,
        timestamp: int = None,
        ):
            self.tree_hash = tree_hash
            self.parent_hashes = parent_hashes
            self.author = author
            self.committer = committer
            self.message = message
            self.timestamp = timestamp or int(time.time())
            
            content = self._serialize_commit()
            super().__init__("commit", content)
        
    def _serialize_commit(self):
            lines = [f"tree {self.tree_hash}"]
            for parent in self.parent_hashes:
                lines.append(f"parent {parent}")
            
            lines.append(f"author {self.author} {self.timestamp} +0000")
            lines.append(f"committer {self.committer} {self.timestamp} +0000")
            lines.append("")
            lines.append(self.message)
            
            return "\n".join(lines).encode()
            #.encode to convert to bytes
            
    @classmethod
    def from_content(cls,content: bytes) -> Commit:
        lines = content.decode().split("\n")
        tree_hash = None
        parent_hashes =[]
        author = None
        committer = None
        message_start = 0
        
        for i,line in enumerate(lines):
            if line.startswith("tree "):
                tree_hash = line[5:]
            elif line.startswith("parent "):
                parent_hashes.append(line[7:])
            elif line.startswith("author "):
                author_parts = line[7:].rsplit(" ",2)
                author = author_parts[0]
                timestamp = int(author_parts[1])
            elif line.startswith("committer "):
                committer_parts = line[10:].rsplit(" ",2)
                committer = committer_parts[0]
            elif line=="":
                message_start = i+1
                break
        message ="\n".join(lines[message_start:])
        commit = cls(tree_hash,parent_hashes,author,committer,message,timestamp)
        return commit            
        
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
                blob = Blob(blob_obj.content)
                file_path.write_bytes(blob.content)
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
                    
                # for removing empty directory 
                # elif file_path.is_dir():
                #     if not any(file_path.iterdir()):
                #       file_path.rmdir()
            except Exception:
                pass
        target_commit_obj = self.load_object(target_commit_hash)
        target_commit = Commit.from_content(target_commit_obj.content)
        
        if target_commit.tree_hash:
            self.restore_tree(target_commit.tree_hash,self.path)
        
        self.save_index({})
            
def main():
    parser = argparse.ArgumentParser(
        description="PyGit - A simpe git clone!")
    
    subparsers = parser.add_subparsers(
            dest="command",
            help="Available commands"
        )
        
    # init command
    init_parser = subparsers.add_parser("init", help="Initialize a new repository")
    
    # add command  
    add_parser = subparsers.add_parser("add", help="Add files and directories to the staging area")
        
    
    add_parser.add_argument("paths", nargs="+", help="Files and directories to add")
    
    # commit command
    commit_parser = subparsers.add_parser(
        "commit",help="Create a new commit"
    )
    commit_parser.add_argument("-m","--message", help="Commit message", required=True,)
    
    commit_parser.add_argument("--author",help="Author name and email",)
    
    # checkout command
    checkout_parser = subparsers.add_parser("checkout", help="Move/Create a new branch")
    checkout_parser.add_argument(
        "branch", help="Branch to switch to")
    checkout_parser.add_argument(
        "-b",
        "--create-branch",
        action="store_true",
        help="Create and switch to a new branch",
    )
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return
      
    repo  = Repository()  
    try:
        if args.command == "init":
            if not repo.init():
                print("Repository already exists")
                return 
        elif args.command =="add":
            if not repo.git_dir.exists():
                print("Not a git repository")
                return 
            for path in args.paths:
                repo.add_path(path)    
        elif args.command =="commit":
            if not repo.git_dir.exists():
                print("Not a git repository")
                return 
            
            author = args.author or "PyGit user <user@pygit.com>"
            repo.commit(args.message, author)
        elif args.command == "checkout":
            if not repo.git_dir.exists():
                print("Not a git repository")
                return 
            repo.checkout(args.branch,args.create_branch)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    print(args)
    
main()
