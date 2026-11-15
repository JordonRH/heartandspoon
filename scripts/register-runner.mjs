import { execFileSync, spawnSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
process.chdir(fileURLToPath(new URL('..', import.meta.url)));
mkdirSync('deploy-runner-state',{recursive:true,mode:0o700});
// The registration token is consumed only in process memory and a temporary container.
// No command, API response, environment dump or runner diagnostics are printed.
let token;
try { token = execFileSync('gh',['api','--method','POST','repos/JordonRH/heartandspoon/actions/runners/registration-token','--jq','.token'],{encoding:'utf8',stdio:['ignore','pipe','pipe']}).trim(); }
catch { throw new Error('GitHub runner registration token request failed; no response displayed.'); }
const result = spawnSync('docker',['compose','-f','compose.runner.yml','run','--rm','--no-deps','-T','-e','RUNNER_TOKEN','runner','--register'],{env:{...process.env,RUNNER_TOKEN:token},stdio:['ignore','pipe','pipe']});
token = undefined;
if (result.status !== 0) throw new Error('Runner registration failed; potentially sensitive diagnostics were not displayed.');
console.log('Dedicated Hearth & Spoon runner registered. No token displayed or saved in the repository.');
