/* cloud-config.js —— AI 通道配置
 *
 * 由平台下发的公开配置写入。这两个值是**唯一允许出现在前端**的凭据：
 *   · endpoint        —— 服务端地址（同时用于 Origin 精确匹配校验）
 *   · publishableKey  —— 标识这个应用，**本身不携带任何权限**
 *                        （服务端会校验请求 Origin 必须精确匹配，因此它放在源码里是安全的）
 *
 * ⚠️ 绝对不允许写进本文件的：环境 id、provider key、任何形如 Bearer <server-key> 的东西。
 *    如果哪天某种写法要求前端持有长期密钥，那是写法错了，不是文件该改。
 *
 * 保持 null 时应用会自动降级到「用户自带 Key」，核心诊断功能完全不受影响。
 * 重新生成/更新：由平台在开通或重新发布云服务时写入，不需要手工编辑。
 */
window.__CLOUD_CONFIG__ = {
  endpoint: "https://question-doctor.app.workbuddy.host",
  publishableKey: "wbpk_0WGpK35PYF4VEZsiTiaxzQ_Pe2av9GPBsp2gVjMGrtfXQqSsX50LrnI",
};
