class OscError(BaseException):
    pass


class PlatformNotSupported(BaseException):
    pass


class CsoundNotFound(BaseException):
    pass


class CsoundConnectionError(BaseException):
    pass


class CsoundRestart(BaseException):
    pass


class GuiConnectionError(BaseException):
    pass