import {parentPort, workerData} from 'node:worker_threads';
import {mergePlan} from './merge.mjs';
parentPort.postMessage(mergePlan(workerData.base, workerData.local, workerData.incoming));
