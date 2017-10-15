#!/usr/bin/python

import calendar
import codecs
import os
import errno
import sys
import argparse
import pyrfc3339 as rfc3339
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

class EventCommitter:

    def __init__(self, gd, opts, repo):
        self.gd = gd
        self.opts = opts
        self.repo = repo
        self.last_commit = None

    @staticmethod
    def prep_directory_for_file(filepath):
        try:
            os.makedirs(os.path.dirname(filepath))
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise

    def commit_revision(self, filepath, rev):
        EventCommitter.prep_directory_for_file(filepath)
        with open(filepath, "w") as fd:
            if 'exportLinks' in rev and not self.opts.raw:
                r = None
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
        # Commit changes to repository
        self.repo.index.add(os.path.relpath(filepath, self.repo.workdir))
        self.repo.index.write()
        tree = self.repo.index.write_tree()
        mt = rfc3339.parse(rev["modifiedDate"])
        author = git.Signature(rev["lastModifyingUser"]["displayName"], rev["lastModifyingUser"]["emailAddress"], calendar.timegm(mt.utctimetuple()), mt.utcoffset().seconds/60)
        parents = [] if self.last_commit is None else [self.last_commit]
        message = 'revision from %s' % rev['modifiedDate']
        self.last_commit = self.repo.create_commit("refs/heads/master", author, author, message, tree, parents)
        logging.info("Commit revision: %s : %s", self.last_commit, message)

    def commit_comment(self, filepath, comment):
        EventCommitter.prep_directory_for_file(filepath)
        with codecs.open(filepath, "w", "utf8") as fd:
            if "context" in comment:
                fd.write(u"#Context\n%s\n\n" % comment["context"]["value"])
            fd.write(u"---\n##Comment by %s at %s:\n%s\n\n" % (comment["author"]["displayName"], comment["createdDate"], comment["content"]))
        # Commit changes to repository
        self.repo.index.add(os.path.relpath(filepath, self.repo.workdir))
        self.repo.index.write()
        tree = self.repo.index.write_tree()
        mt = rfc3339.parse(comment["createdDate"])
        author = git.Signature(comment["author"]["displayName"], "n/a", calendar.timegm(mt.utctimetuple()), mt.utcoffset().seconds/60)
        parents = [] if self.last_commit is None else [self.last_commit]
        message = "Comment by %s" % comment["author"]["displayName"]
        self.last_commit = self.repo.create_commit("refs/heads/master", author, author, message, tree, parents)
        logging.info("Commit comment: %s : %s", self.last_commit, message)

    def commit_reply(self, filepath, reply):
        EventCommitter.prep_directory_for_file(filepath)
        with codecs.open(filepath, "a", "utf8") as fd:
            if "verb" in reply:
                if reply["verb"] == "resolve":
                    fd.write(u"---\n##Resolved by %s at %s:\n\n" % (reply["author"]["displayName"], reply["createdDate"]))
                    message = "Resolved by %s" % reply["author"]["displayName"]
                elif reply["verb"] == "reopen":
                    fd.write(u"---\n##Reopened by %s at %s:\n\n" % (reply["author"]["displayName"], reply["createdDate"]))
                    message = "Reopened by %s" % reply["author"]["displayName"]
            else:
                fd.write(u"---\n##Reply by %s at %s:\n%s\n\n" % (reply["author"]["displayName"], reply["createdDate"], reply["content"]))
                message = "Reply by %s" % reply["author"]["displayName"]
        # Commit changes to repository
        self.repo.index.add(os.path.relpath(filepath, self.repo.workdir))
        self.repo.index.write()
        tree = self.repo.index.write_tree()
        mt = rfc3339.parse(reply["createdDate"])
        author = git.Signature(reply["author"]["displayName"], "n/a", calendar.timegm(mt.utctimetuple()), mt.utcoffset().seconds/60)
        parents = [] if self.last_commit is None else [self.last_commit]
        self.last_commit = self.repo.create_commit("refs/heads/master", author, author, message, tree, parents)
        logging.info("Commit reply: %s : %s", self.last_commit, message)

    def commit(self, events):
        for event in events:
            filepath = os.path.join(self.repo.workdir, event["xFilePath"])
            if event["kind"] == "drive#revision":
                self.commit_revision(filepath, event)
            elif event["kind"] == "drive#comment":
                self.commit_comment(filepath, event)
            elif event["kind"] == "drive#commentReply":
                self.commit_reply(filepath, event)
            else:
                raise ValueError("unexpected event kind: %s" % event["kind"])

class EventScanner:

    def __init__(self, gd, opts):
        self.gd = gd
        self.opts = opts
        self._events = []

    def scan_file(self, fid, filepath):
        # Scan revisions
        for rev in self.gd.revisions(fid):
            rev["xFilePath"] = filepath
            self._events.append(rev)
        # Scan comments
        for comment in self.gd.comments(fid):
            comment["xFilePath"] = os.path.join(filepath + "_comments", comment["commentId"].lower() + ".md")
            self._events.append(comment)
            for reply in comment["replies"]:
                reply["xFilePath"] = comment["xFilePath"]
                self._events.append(reply)

    def scan_folder(self, fid, filepath):
        # Process folder
        for child in self.gd.children(fid):
            self.scan(child["id"], filepath)

    def scan(self, rid, parent_path=""):
        md = gd.get_file_metadata(rid)
        filepath = os.path.join(parent_path, md["title"].lower().replace(" ", "_"))
        if md["mimeType"] == "application/vnd.google-apps.folder":
            logging.info("Process folder: %s : %s : %s", rid, md["title"], filepath)
            self.scan_folder(rid, filepath)
        else:
            logging.info("Process file: %s : %s : %s", rid, md["title"], filepath)
            self.scan_file(rid, filepath)

    @staticmethod
    def _event_sort_key(event):
        if event["kind"] == "drive#revision":
            return rfc3339.parse(event["modifiedDate"])
        elif event["kind"] == "drive#comment" or event["kind"] == "drive#commentReply":
            return rfc3339.parse(event["createdDate"])
        else:
            raise ValueError("unexpected event kind: %s" % event["kind"])

    @property
    def events(self):
        self._events.sort(key=EventScanner._event_sort_key)
        return self._events

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

    # Scan for events.
    s = EventScanner(gd, opts)
    s.scan(opts.id)
    logging.info("Scan completed, found %d events", len(s.events))
    # Initialize the git repository.
    repo = git.init_repository(opts.output)
    logging.info("Created repository at %s", repo.workdir)
    c = EventCommitter(gd, opts, repo)
    c.commit(s.events)
    logging.info("Complete!")
