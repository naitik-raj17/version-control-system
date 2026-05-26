from __future__ import annotations
import argparse
import sys
from pathlib import Path
import json
import hashlib
import zlib
import time
from typing import Dict,List,Tuple,Optional
from rich import print


from pygit.core.objects import (
    GitObject,
    Blob,
    Tree,
    Commit
)     

from pygit.core.repository import Repository

        

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

    # status command
    status_parser = subparsers.add_parser(
        "status",
        help = "Show repository status"
    )


    # log parser 
    log_parser = subparsers.add_parser(
        "log",
        help = "Show commit history"
    )

    log_parser.add_argument(
        "--oneline",
        action="store_true",
        help="Show compact log format"
    )

    log_parser.add_argument(
        "--graph",
        action="store_true",
        help="Show commit graph"
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

        elif args.command == "status":
            if not repo.git_dir.exists():
                print("Not a git repository")
                return 
            repo.status()
        
        elif args.command == "log":
            if not repo.git_dir.exists():
                print("Not a git repository")
                return 
            repo.log(args.oneline,args.graph)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    # print(args)
    
main()
