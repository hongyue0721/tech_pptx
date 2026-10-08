#!/usr/bin/env bash
# T02 离线Node环境搭建脚本（沙箱无外网的固化方案）
# 依赖：本机 hongyue_bolg 工程的 .pnpm store（vue3.5.41/vite8.2.2全链已验证）
# 用法：在探针工程目录下执行 bash setup_offline_node_env.sh
set -euo pipefail

BLOG=/home/hongyue/Projects/hongyue_bolg/node_modules/.pnpm
[ -d "$BLOG" ] || { echo "缺少依赖源: $BLOG"; exit 4; }

rm -rf node_modules
mkdir -p node_modules/@vitejs node_modules/@vue node_modules/@esbuild node_modules/@rolldown

# vite主包+运行时依赖（vite8=rolldown底层，平台绑定必须补）
ln -s "$BLOG/vite@8.2.2_esbuild@0.28.2_jiti@2.7.0/node_modules/vite" node_modules/vite
for dep in esbuild@0.28.2 jiti@2.7.0 lightningcss@1.33.0 picomatch@4.0.5 postcss@8.5.26 rolldown@1.2.5 tinyglobby@0.2.17; do
  name=$(echo "$dep" | sed 's/@[0-9].*//')
  ln -s "$BLOG/$dep/node_modules/$name" "node_modules/$name"
done
ln -s "$BLOG/@esbuild+linux-x64@0.28.2/node_modules/@esbuild/linux-x64" node_modules/@esbuild/linux-x64
ln -s "$BLOG/@rolldown+binding-linux-x64-gnu@1.2.5/node_modules/@rolldown/binding-linux-x64-gnu" node_modules/@rolldown/binding-linux-x64-gnu
ln -s "$BLOG/@oxc-project+runtime@*" node_modules/@oxc-project 2>/dev/null || {
  src=$(ls -d "$BLOG"/@oxc-project+runtime@*/node_modules/@oxc-project 2>/dev/null | head -1)
  [ -n "$src" ] && ln -s "$src" node_modules/@oxc-project
}

# vue全家桶
ln -s "$BLOG/vue@3.5.41/node_modules/vue" node_modules/vue
ln -s "$BLOG/@vitejs+plugin-vue@6.0.8_vite@8.2.2_esbuild@0.28.2_jiti@2.7.0__vue@3.5.41/node_modules/@vitejs/plugin-vue" node_modules/@vitejs/plugin-vue
for dep in compiler-core compiler-dom compiler-sfc compiler-ssr reactivity runtime-core runtime-dom server-renderer shared; do
  src=$(ls -d "$BLOG/@vue+$dep@3.5.41/node_modules/@vue/$dep" 2>/dev/null | head -1)
  [ -z "$src" ] && src=$(ls -d "$BLOG"/@vue+$dep@*/node_modules/@vue/$dep 2>/dev/null | head -1)
  [ -n "$src" ] && ln -s "$src" "node_modules/@vue/$dep" || echo "warn: 缺 @vue/$dep"
done

echo "离线node_modules软链搭建完成（vue3.5.41 + vite8.2.2 + @vitejs/plugin-vue6.0.8）"
