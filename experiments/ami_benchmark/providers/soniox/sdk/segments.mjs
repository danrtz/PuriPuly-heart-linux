import { segmentTranscript } from '@soniox/node';

let input = '';
for await (const chunk of process.stdin) input += chunk;
const tokens = JSON.parse(input);
process.stdout.write(JSON.stringify(segmentTranscript(tokens, { group_by: ['speaker'] })));
