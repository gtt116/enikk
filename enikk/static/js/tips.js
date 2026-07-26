/**
 * User-facing tips that rotate in the chat footer.
 * Each tip has a zh-CN and en translation.
 */
const TIPS = [
  {
    'zh-CN': '🛑 发送 "/stop" 停止当前任务',
    en: '🛑 Send "/stop" to stop current task',
  },
  {
    'zh-CN': '👆 Agent 找不到按钮？你可以教它：截图中的 [244, 234] 就是坐标，告诉它「点击 [244, 234]」即可。',
    en: '👆 Agent can\'t find the button? You can teach it: [244, 234] in the screenshot is the coordinate. Tell it "click [244, 234]".',
  },
  {
    'zh-CN': '📷 IM 里发送 "/images" 可以开关图片的回显',
    en: '📷 Send "/images" in IM to toggle image display',
  },
  {
    'zh-CN': '🔐 请使用管理员权限运行 Enikk，如此它才能启动 app 进程。',
    en: '🔐 Please run Enikk as administrator so it can launch app processes.',
  },
  {
    'zh-CN': '🖱️ Enikk 运行过程中会挪动鼠标指针哦，建议使用 IM 遥控 Enikk，这样你们两就不会因为抢鼠标而吵架',
    en: '🖱️ Enikk will move the mouse pointer during operation. Consider using IM to control it remotely, so you won\'t fight over the mouse',
  },
  {
    'zh-CN': '⏰ 你可以让 Agent 创建定时任务，比如「每天早上 9 点帮我领取月卡」，它会自动设置 cron 定时执行。',
    en: '⏰ You can ask Agent to create scheduled tasks, e.g. "claim daily rewards every day at 9am" — it will set up a cron job automatically.',
  },
  {
    'zh-CN': '📚 Agent 可以创建和管理技能（Skills），把常用操作封装成可复用的指令，比如「创建一个一键日常的技能」。',
    en: '📚 Agent can create and manage Skills — reusable commands for common workflows. Try "create a skill for my daily routine".',
  },
];
