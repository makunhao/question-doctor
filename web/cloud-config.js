/* cloud-config.js —— AI 通道配置（部署时由云服务激活步骤写入）
 *
 * 这里放的是 publicConfig.endpoint 与 publicConfig.publishableKey。
 * 这两个值**只用于初始化客户端**；服务端会做 Origin 精确匹配校验，
 * publishableKey 本身不携带任何权限，因此可以出现在前端源码里。
 * 除这两个值以外的任何密钥（环境 id、provider key、token）都**绝不允许**写进本文件。
 *
 * 保持 null 时，应用会走「用自己的 Key」的降级路径，规则引擎功能完全不受影响。
 */
window.__CLOUD_CONFIG__ = null;
