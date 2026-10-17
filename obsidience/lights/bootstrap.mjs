// Configure before importing matter.js; native fabric state must never reach its default filesystem.
import { config } from '@matter/nodejs/config';
config.loadProcessArgv = false;
config.loadProcessEnv = false;
config.loadConfigFile = false;
config.installFilesystem = false;
config.trapProcessSignals = false;
config.trapUnhandledErrors = false;
config.setProcessExitCodeOnError = false;
