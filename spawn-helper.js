#!/usr/bin/env node
/**
 * spawn-helper.js - 通过 Node.js 调用 OpenClaw 内部 spawn 函数
 * 
 * 用法: node spawn-helper.js <task> [label] [timeout]
 */
const path = require('path');

// 加载 OpenClaw 的 auth-profiles bundle
const openclawDist = path.join(
  process.env.OPENCLAW_DIR || 'C:\\Program Files\\QClaw\\resources\\openclaw',
  'node_modules\\openclaw\\dist\\auth-profiles-B4lxY7jj.js'
);

// 创建一个简化的 spawn 环境
async function main() {
  const args = process.argv.slice(2);
  if (args.length < 1) {
    console.error('Usage: node spawn-helper.js <task> [label] [timeout]');
    process.exit(1);
  }
  
  const [task, label = 'spawn-helper', timeout = '60'] = args;
  const timeoutSec = parseInt(timeout, 10);
  
  // 加载 OpenClaw bundle
  let spawnSubagentDirect;
  try {
    require(openclawDist);
    // 检查是否导出了 spawnSubagentDirect
    const mod = require(openclawDist);
    console.log('Loaded module keys:', Object.keys(mod).slice(0, 20));
  } catch (e) {
    console.log('Cannot load module directly:', e.message);
  }
  
  // 直接在 bundle 中查找 spawnSubagentDirect
  const fs = require('fs');
  const bundle = fs.readFileSync(openclawDist, 'utf-8');
  const idx = bundle.indexOf('async function spawnSubagentDirect');
  if (idx > 0) {
    console.log('Found spawnSubagentDirect at index', idx);
    // 提取函数体前 500 字符
    console.log(bundle.substring(idx, idx + 500));
  }
}

main().catch(console.error);
