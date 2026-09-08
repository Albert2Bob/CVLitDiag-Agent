import { createRouter, createWebHistory } from "vue-router";
import { readLocal } from "../utils/storage";
import LoginView from "../views/LoginView.vue";
import ProjectsView from "../views/ProjectsView.vue";
import ChatView from "../views/ChatView.vue";
const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/projects" },
    { path: "/login", component: LoginView },
    { path: "/projects", component: ProjectsView },
    { path: "/chat/:project_id", component: ChatView },
    { path: "/:pathMatch(.*)*", redirect: "/projects" },
  ],
});
router.beforeEach((to) => {
  if (to.path !== "/login" && !readLocal("vision-research.user", null)?.user_id)
    return "/login";
});
export default router;
