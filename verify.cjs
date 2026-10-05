'use strict'
const fs = require('node:fs')
const versions={'city-1':require('./static/js/engine-city-1.js'),'city-2':require('./static/js/engine-city-2.js'),'city-3':require('./static/js/engine-city-3.js'),'city-4':require('./static/js/engine-city-4.js')}
try {
  const data = JSON.parse(fs.readFileSync(0, 'utf8'))
  const engine=versions[data.version]
  if(!engine)throw Error('Unsupported engine')
  if(data.version!==engine.VERSION||data.map!==engine.MAP)throw Error('Unsupported engine or map')
  process.stdout.write(JSON.stringify(engine.replay(data.seed,data.config,data.inputs)))
} catch (e) { process.stderr.write('Replay rejected'); process.exitCode=1 }
