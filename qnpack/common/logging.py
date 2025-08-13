import os
import sys
import logging
import logging.config


def qnpack_log_formatter():
    config_logformat = "{asctime} {name} {levelname} {message}"
    return logging.Formatter(fmt=config_logformat,
                             datefmt='%H:%M:%S',
                             style='{')


def setup_default_logging(log, level=logging.INFO, logfile=None):
    """
    Configures the logging by setting the output stream to stdout and
    configures log level and log format.
    """

    if logfile:
        filehandler = logging.FileHandler(logfile, mode='w')
        filehandler.setFormatter(qnpack_log_formatter())
        filehandler.setLevel(level)
        logging.basicConfig(handlers=[filehandler])
        log.setLevel(level)
    else:
        stdouthandler = logging.StreamHandler(stream=sys.stdout)
        stdouthandler.setFormatter(qnpack_log_formatter())
        stdouthandler.setLevel(level)
        logging.basicConfig(handlers=[stdouthandler])
        log.setLevel(level)


def setup_logging(name=__name__, level=logging.INFO, config=None, logfile=None):
    """
    Configures the logging by setting the output stream to stdout and
    configures log level and log format.
    """

    log = logging.getLogger(name)
    configfiles = list()
    if config:
        configfiles.append(config)

    has_config = False
    for configfile in configfiles:
        try:
            logging.config.fileConfig(configfile, disable_existing_loggers=False)
            has_config = True
        except Exception as e:
            has_config = False
        if has_config:
            break

    if not has_config:
        setup_default_logging(log, level, logfile)
    return log
