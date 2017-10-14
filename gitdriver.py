#!/usr/bin/python

import os
import sys
import argparse
import subprocess
import shutil
import yaml

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

def process_file(gd, fid, filepath):
    # Iterate over the revisions (from oldest to newest).
    for rev in gd.revisions(fid):
        with open(filepath, 'w') as fd:
            if 'exportLinks' in rev and not opts.raw:
                for mt in opts.mime_type:
                    if mt in rev["exportLinks"]:
                        r = gd.session.get(rev["exportLinks"][mt])
                        break
                if r is None:
                    raise KeyError("mime type(s) %s not found in %s" % (opts.mime_type, rev["exportLinks"].keys()))
            elif 'downloadUrl' in rev:
                # Otherwise, if there is a downloadUrl, use that.
                r = gd.session.get(rev['downloadUrl'])
            else:
                raise KeyError('unable to download revision')
            # Write file content into local file.
            for chunk in r.iter_content():
                fd.write(chunk)
        # Commit changes to repository.
        subprocess.call(['git', 'add', filepath])
        subprocess.call(['git', 'commit', '-m',
            'revision from %s' % rev['modifiedDate']])

def process_folder(gd, fid, filepath):
    os.mkdir(filepath)
    # Process folder
    for child in gd.children(fid):
        process(gd, child["id"], filepath)

def process(gd, rid, parent_path):
    md = gd.get_file_metadata(rid)
    filepath = os.path.join(parent_path, md["title"])
    if md["mimeType"] == "application/vnd.google-apps.folder":
        logging.info("Process folder: %s : %s : %s", rid, md["title"], filepath)
        process_folder(gd, rid, filepath)
    else:
        logging.info("Process file: %s : %s : %s", rid, md["title"], filepath)
        process_file(gd, rid, filepath)

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
    logging.info("Creating output repsitory at %s", opts.output)
    os.chdir(opts.output)
    subprocess.call(['git','init'])

    # Begin processing.
    process(gd, opts.id, opts.output)
    logging.debug("Process complete!")
