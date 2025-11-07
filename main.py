import sys
from PyQt5.QtWidgets import QApplication
from ui.bootstrap import AppBootstrap

if __name__ == "__main__":
    app = QApplication(sys.argv)
    bootstrap = AppBootstrap(app)
    bootstrap.start()
    sys.exit(app.exec_())