from MinecraftCurseModDownload import MinecraftCurseModDownload
import sys

if __name__ == "__main__":
    mc = MinecraftCurseModDownload()
    mc.download(sys.argv[1])
