import json, hashlib, ntpath, os, sys
import pbincli.actions, pbincli.settings
from sjcl import SJCL

from base64 import b64encode, b64decode
from mimetypes import guess_type
from pbincli.transports import privatebin
from pbincli.utils import PBinCLIException, check_readable, check_writable, json_load_byteified


# Initialise settings
pbincli.settings.init()


def path_leaf(path):
    head, tail = ntpath.split(path)
    return tail or ntpath.basename(head)


def send(args):
    if args.comment:
        text = args.comment
    elif args.file:
        text = "Sending a file to you!"
    else:
        print("Nothing to send!")
        sys.exit(1)

    # Formatting request
    request = {'expire':args.expire,'formatter':args.format,'burnafterreading':int(args.burn),'opendiscussion':int(args.discus)}

    passphrase = b64encode(os.urandom(32))
    if args.debug: print("Passphrase:\t{}".format(passphrase))

    # If we set PASSWORD variable
    if args.password:
        digest = hashlib.sha256(args.password.encode("UTF-8")).hexdigest()
        password = passphrase + digest.encode("UTF-8")
    else:
        password = passphrase

    if args.debug: print("Password:\t{}".format(password))

    # Encrypting text (comment)
    cipher = SJCL().encrypt(text.encode("utf-8"), password, mode='gcm')

    # TODO: should be implemented in upstream
    for k in ['salt', 'iv', 'ct']: cipher[k] = cipher[k].decode()

    request['data'] = json.dumps(cipher, ensure_ascii=False).replace(' ','')

    # If we set FILE variable
    if args.file:
        check_readable(args.file)
        with open(args.file, "rb") as f:
            contents = f.read()
            f.close()
        mime = guess_type(args.file)
        if args.debug: print("Filename:\t{}\nMIME-type:\t{}".format(path_leaf(args.file), mime[0]))

        file = "data:" + mime[0] + ";base64," + b64encode(contents).decode()
        filename = path_leaf(args.file)

        cipherfile = SJCL().encrypt(file.encode("utf-8"), password, mode='gcm')
        # TODO: should be implemented in upstream
        for k in ['salt', 'iv', 'ct']: cipherfile[k] = cipherfile[k].decode()
        cipherfilename = SJCL().encrypt(filename.encode("utf-8"), password, mode='gcm')
        for k in ['salt', 'iv', 'ct']: cipherfilename[k] = cipherfilename[k].decode()

        request['attachment'] = json.dumps(cipherfile, ensure_ascii=False).replace(' ','')
        request['attachmentname'] = json.dumps(cipherfilename, ensure_ascii=False).replace(' ','')

    if args.debug: print("Request:\t{}".format(request))

    # If we use dry option, exit now
    if args.dry: sys.exit(0)

    server = pbincli.settings.server
    result = privatebin().post(request)

    if args.debug: print("Response:\t{}\n".format(result.decode("UTF-8")))

    try:
        result = json.loads(result)
    except ValueError as e:
        print("PBinCLI Error: {}".format(e))
        sys.exit(1)

    if 'status' in result and not result['status']:
        print("Paste uploaded!\nPasteID:\t{}\nPassword:\t{}\nDelete token:\t{}\n\nLink:\t\t{}?{}#{}".format(result['id'], passphrase.decode(), result['deletetoken'], server, result['id'], passphrase.decode()))
    elif 'status' in result and result['status']:
        print("Something went wrong...\nError:\t\t{}".format(result['message']))
        sys.exit(1)
    else:
        print("Something went wrong...\nError: Empty response.")
        sys.exit(1)


def get(args):
    pasteid, passphrase = args.pasteinfo.split("#")

    if pasteid and passphrase:
        if args.debug: print("PasteID:\t{}\nPassphrase:\t{}".format(pasteid, passphrase))

        if args.password:
            digest = hashlib.sha256(args.password.encode("UTF-8")).hexdigest()
            password = passphrase + digest.encode("UTF-8")
        else:
            password = passphrase

        if args.debug: print("Password:\t{}".format(password))

        result = privatebin().get(pasteid)
    else:
        print("PBinCLI error: Incorrect request")
        sys.exit(1)

    if args.debug: print("Response:\t{}\n".format(result.decode("UTF-8")))

    try:
        result = json.loads(result)
    except ValueError as e:
        print("PBinCLI Error: {}".format(e))
        sys.exit(1)

    if 'status' in result and not result['status']:
        print("Paste received! Text inside:")
        data = json.loads(result['data'])

        if args.debug: print("Text:\t{}\n".format(data))

        text = SJCL().decrypt(data, password)
        print("{}\n".format(text.decode()))

        check_writable("paste.txt")
        with open("paste.txt", "wb") as f:
            f.write(text)
            f.close

        if 'attachment' in result and 'attachmentname' in result:
            print("Found file, attached to paste. Decoding it and saving")

            cipherfile = json.loads(result['attachment']) 
            cipherfilename = json.loads(result['attachmentname'])

            if args.debug: print("Name:\t{}\nData:\t{}".format(cipherfilename, cipherfile))

            attachmentf = SJCL().decrypt(cipherfile, password)
            attachmentname = SJCL().decrypt(cipherfilename, password)

            attachment = str(attachmentf.split(',', 1)[1:])
            file = b64decode(attachment)
            filename = attachmentname

            print("Filename:\t{}\n".format(filename))

            check_writable(filename)
            with open(filename, "wb") as f:
                f.write(file)
                f.close

        if 'burnafterreading' in result['meta'] and result['meta']['burnafterreading']:
            print("Burn afrer reading flag found. Deleting paste...")
            result = privatebin().delete(pasteid, 'burnafterreading')

            if args.debug: print("Delete response:\t{}\n".format(result.decode("UTF-8")))

            try:
                result = json.loads(result)
            except ValueError as e:
                print("PBinCLI Error: {}".format(e))
                sys.exit(1)

            if 'status' in result and not result['status']:
                print("Paste successfully deleted!")
            elif 'status' in result and result['status']:
                print("Something went wrong...\nError:\t\t{}".format(result['message']))
                sys.exit(1)
            else:
                print("Something went wrong...\nError: Empty response.")
                sys.exit(1)

    elif 'status' in result and result['status']:
        print("Something went wrong...\nError:\t\t{}".format(result['message']))
        sys.exit(1)
    else:
        print("Something went wrong...\nError: Empty response.")
        sys.exit(1)


def delete(args):
    pasteid = args.paste
    token = args.token

    if args.debug: print("PasteID:\t{}\nToken:\t\t{}".format(pasteid, token))

    result = privatebin().delete(pasteid, token)

    if args.debug: print("Response:\t{}\n".format(result.decode("UTF-8")))

    try:
        result = json.loads(result)
    except ValueError as e:
        print("PBinCLI Error: {}".format(e))
        sys.exit(1)
    
    if 'status' in result and not result['status']:
        print("Paste successfully deleted!")
    elif 'status' in result and result['status']:
        print("Something went wrong...\nError:\t\t{}".format(result['message']))
        sys.exit(1)
    else:
        print("Something went wrong...\nError: Empty response.")
        sys.exit(1)
