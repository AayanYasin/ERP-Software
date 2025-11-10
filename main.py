import sys
from PyQt5.QtCore import Qt, QCoreApplication
from PyQt5.QtWidgets import QApplication
from ui.bootstrap import AppBootstrap

if __name__ == "__main__":
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    bootstrap = AppBootstrap(app)
    bootstrap.start()
    sys.exit(app.exec_())