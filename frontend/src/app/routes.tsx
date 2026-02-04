import React from "react";
import { createBrowserRouter } from "react-router-dom";
import Overview from "../pages/Overview";
import VerifyQueue from "../pages/VerifyQueue";
import Upload from "../pages/Upload";
import App from "./App";

export const router = createBrowserRouter([
  {
    element: <App />,
    children: [
      { path: "/", element: <Overview /> },
      { path: "/verify", element: <VerifyQueue /> },
      { path: "/upload", element: <Upload /> },
    ],
  },
]);
