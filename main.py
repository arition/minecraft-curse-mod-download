from MinecraftCurseModDownload import MinecraftCurseModDownload
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "input_file", help="Input mod list file or mod list lock file")
    parser.add_argument("-u", "--update", help="", action="store_true")
    args = parser.parse_args()
    mc = MinecraftCurseModDownload()
    if args.input_file.endswith(".lock"):
        mc.download_locked_version(args.input_file)
    else:
        mc.download(args.input_file, args.update)
