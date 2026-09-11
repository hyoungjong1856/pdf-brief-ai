import { BrowserRouter, Route, Routes } from "react-router";
import HomePage from "./pages/HomePage";
import DeveloperPage from "./pages/DeveloperPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route>
          <Route index element={<HomePage />} />
          <Route path="developer" element={<DeveloperPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
