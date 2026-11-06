import {storyRequest} from './story-bridge.mjs';
let input = '';
process.stdin.setEncoding('utf8');
try {
  for await (const chunk of process.stdin) {
    input += chunk;
    if (input.length > 16 * 1024 * 1024) throw Error('Story request too large');
  }
  process.stdout.write(JSON.stringify(storyRequest(JSON.parse(input))));
} catch (error) { process.stderr.write(error.message+'\n'); process.exitCode=1; }
