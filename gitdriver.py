#!/usr/bin/python

import os
import sys
import argparse
import subprocess
import shutil
import yaml
import pygit2 as git

from drive import GoogleDrive, DRIVE_RW_SCOPE

import logging
import json

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--config', '-c', default='gd.conf')
    p.add_argument('--verbose', '-v', action='store_true')
    p.add_argument('--force', '-f', action='store_true', help='force overwrite of old output repository')
    p.add_argument('--output', '-o', required=True, help='directory where to output git repository')
    p.add_argument('--mime-type', dest='mime_type', action='append', required=True, help='preferred mime types')
    p.add_argument('--raw', '-R', action='store_true', help='Download original document if possible.')
    p.add_argument('id', help='ID of document or folder')
    return p.parse_args()

class Processor:

    def __init__(self, gd, opts, repo):
        self.gd = gd
        self.opts = opts
        self.repo = repo
        self.tree_builder = repo.TreeBuilder()
        self.last_commit = None

    def process_file(self, fid, filepath):
        # Iterate over the revisions (from oldest to newest).
        for rev in self.gd.revisions(fid):
            with open(filepath, 'w') as fd:
                if 'exportLinks' in rev and not self.opts.raw:
                    for mt in self.opts.mime_type:
                        if mt in rev["exportLinks"]:
                            r = self.gd.session.get(rev["exportLinks"][mt])
                            break
                    if r is None:
                        raise KeyError("mime type(s) %s not found in %s" % (self.opts.mime_type, rev["exportLinks"].keys()))
                elif 'downloadUrl' in rev:
                    # Otherwise, if there is a downloadUrl, use that.
                    r = self.gd.session.get(rev['downloadUrl'])
                else:
                    raise KeyError('unable to download revision')
                # Write file content into local file.
                for chunk in r.iter_content():
                    fd.write(chunk)
            # Commit changes to repository.
            self.repo.index.add(os.path.relpath(filepath, self.repo.workdir))
            self.repo.index.write()
            tree = self.repo.index.write_tree()
            author = git.Signature("Unknown", "unknown email") # TODO use the last modifying user
            parents = [] if self.last_commit is None else [self.last_commit]
            message = 'revision from %s' % rev['modifiedDate']
            self.last_commit = self.repo.create_commit("refs/heads/master", author, author, message, tree, parents)
            logging.info("Commit: %s : %s", self.last_commit, message)

    def process_folder(self, fid, filepath):
        os.mkdir(filepath)
        # Process folder
        for child in self.gd.children(fid):
            self.process(child["id"], filepath)

    def process(self, rid, parent_path):
        md = gd.get_file_metadata(rid)
        filepath = os.path.join(parent_path, md["title"].lower().replace(" ", "_"))
        if md["mimeType"] == "application/vnd.google-apps.folder":
            logging.info("Process folder: %s : %s : %s", rid, md["title"], filepath)
            self.process_folder(rid, filepath)
        else:
            logging.info("Process file: %s : %s : %s", rid, md["title"], filepath)
            self.process_file(rid, filepath)

if __name__ == '__main__':
    opts = parse_args()
    logging.basicConfig(level=logging.DEBUG if opts.verbose else logging.INFO, format=u"%(relativeCreated)dms: %(message)s")

    # Prepare output repository.
    if os.path.exists(opts.output):
        if opts.force:
            shutil.rmtree(opts.output)
        else:
            logging.error("There is already a file/directory at %s, use --force to overwrite", opts.output)
            sys.exit(2)
    os.makedirs(opts.output)

    # Establish our credentials.
    cfg = yaml.load(open(opts.config))
    gd = GoogleDrive(
            client_id=cfg['googledrive']['client id'],
            client_secret=cfg['googledrive']['client secret'],
            scopes=[DRIVE_RW_SCOPE],
            )
    gd.authenticate()

    # Initialize the git repository.
    repo = git.init_repository(opts.output)
    logging.info("Created output repository at %s", repo.workdir)

    # Begin processing.
    p = Processor(gd, opts, repo)
    p.process(opts.id, repo.workdir)
    logging.debug("Process complete!")
