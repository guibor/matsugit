// Explicit setup paths win. Native Windows Python is normally named python.exe.
export function pythonExecutable(env = process.env, platform = process.platform) {
  return env.MATSUGIT_PYTHON || env.FOLIOFORGE_PYTHON || (platform === 'win32' ? 'python' : 'python3');
}

export function pythonEnvironment(env = process.env, platform = process.platform) {
  return platform === 'win32' ? {...env, PYTHONUTF8: '1'} : env;
}
