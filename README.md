## Synopsis

```
usage: gitdriver.py [-h] [--config CONFIG] [--verbose] [--force] --output
                    OUTPUT --mime-type MIME_TYPE [--raw]
                    id

Tool to collect revisions from a Google Drive file or folder into a git
repository.

positional arguments:
  id                    id of google drive document or folder

optional arguments:
  -h, --help            show this help message and exit
  --config CONFIG, -c CONFIG
  --verbose, -v
  --force, -f           force overwrite of old output repository
  --output OUTPUT, -o OUTPUT
                        directory where to output git repository
  --mime-type MIME_TYPE
                        preferred mime types, in order of preference
  --raw, -R             download original document if possible
```

## Dependencies

- `libgit2`: https://libgit2.github.com/

## Google setup

You will need to create an OAuth client id and secret for use with
this application, the Drive API [Python quickstart][] has links to the
necessary steps.

[python quickstart]: https://developers.google.com/drive/v3/web/quickstart/python

## Configuration

In order to make this go you will need to create file named `gd.conf`
where the code can find it (typically the directory in which you're
running the code, but you can also use the `-f` command line option to
specify an alternate location).

The file is a simple YAML document that should look like this:

```
googledrive:
  client id: YOUR_CLIENT_ID
  client secret: YOUR_CLIENT_SECRET
```

Where `YOUR_CLIENT_ID` and `YOUR_CLIENT_SECRET` are replaced with the
appropriate values from Google that you established in the previous
step.
